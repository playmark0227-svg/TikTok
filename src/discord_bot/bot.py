"""Discord Bot 本体

常駐プロセスとして動作。リアクション/メッセージで承認・修正・却下を処理する。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from config.settings import Settings, get_settings
from src.discord_bot.approval_flow import (
    EMOJI_APPROVE,
    EMOJI_REJECT,
    EMOJI_REVISION,
    ApprovalDecision,
    ApprovalQueue,
    ApprovalRequest,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    pass


class DiscordBotError(Exception):
    """Discord Bot エラー"""


class ApprovalBot:
    """承認 Bot ラッパー

    discord.py の Client を内包し、承認依頼を受けて Discord に投稿する。
    """

    def __init__(
        self,
        settings: Settings | None = None,
        queue: ApprovalQueue | None = None,
    ):
        self.settings = settings or get_settings()
        self.queue = queue or ApprovalQueue.instance()
        self._client: Any = None
        self._approval_channel: Any = None
        self._notification_channel: Any = None
        self._request_messages: dict[str, int] = {}  # request_id -> message_id
        self._message_requests: dict[int, str] = {}  # message_id -> request_id
        self._ready = asyncio.Event()
        self._revision_waiting: dict[str, str] = {}  # request_id -> "waiting"

    def _build_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import discord
        except ImportError as e:
            raise DiscordBotError("discord.py がインストールされていません") from e

        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True

        client = discord.Client(intents=intents)

        @client.event
        async def on_ready() -> None:
            logger.info("Discord Bot 起動", user=str(client.user))
            await self._init_channels(client)
            self._ready.set()

        @client.event
        async def on_reaction_add(reaction: Any, user: Any) -> None:
            if user.bot:
                return
            await self._handle_reaction(reaction, user)

        @client.event
        async def on_message(message: Any) -> None:
            if message.author.bot:
                return
            await self._handle_message(message)

        self._client = client
        return client

    async def _init_channels(self, client: Any) -> None:
        if self.settings.discord_approval_channel_id:
            try:
                self._approval_channel = await client.fetch_channel(
                    int(self.settings.discord_approval_channel_id)
                )
            except Exception as e:
                logger.error("承認チャンネル取得失敗", error=str(e))

        if self.settings.discord_notification_channel_id:
            try:
                self._notification_channel = await client.fetch_channel(
                    int(self.settings.discord_notification_channel_id)
                )
            except Exception as e:
                logger.warning("通知チャンネル取得失敗", error=str(e))

    async def start(self) -> None:
        """Bot を起動(ブロッキング)"""
        if self.settings.is_dry_run:
            logger.info("DRY_RUN: Discord Bot 起動スキップ")
            return
        if not self.settings.discord_bot_token:
            raise DiscordBotError("DISCORD_BOT_TOKEN が未設定")
        client = self._build_client()
        await client.start(self.settings.discord_bot_token)

    async def wait_until_ready(self, timeout: float = 30.0) -> None:
        if self.settings.is_dry_run:
            return
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    async def send_approval_request(self, request: ApprovalRequest) -> None:
        """承認依頼を Discord に送信"""
        if self.settings.is_dry_run:
            logger.info(
                "DRY_RUN: 承認依頼を Discord に送信(スキップ)",
                request_id=request.request_id,
            )
            return

        if self._approval_channel is None:
            raise DiscordBotError("承認チャンネルが初期化されていません")

        embed = self._build_embed(request)
        try:
            message = await self._approval_channel.send(
                content=self._build_content(request),
                embed=embed,
            )
            for emoji in (EMOJI_APPROVE, EMOJI_REVISION, EMOJI_REJECT):
                await message.add_reaction(emoji)
            self._request_messages[request.request_id] = message.id
            self._message_requests[message.id] = request.request_id
            logger.info(
                "承認依頼送信",
                request_id=request.request_id,
                message_id=message.id,
            )
        except Exception as e:
            logger.error("Discord 送信失敗", error=str(e))
            raise DiscordBotError(f"Discord 送信失敗: {e}") from e

    async def send_notification(self, message: str, *, embed: Any = None) -> None:
        if self.settings.is_dry_run:
            logger.info("DRY_RUN: 通知スキップ", message=message)
            return
        channel = self._notification_channel or self._approval_channel
        if channel is None:
            logger.warning("通知チャンネルなし、ログのみ", message=message)
            return
        try:
            await channel.send(content=message, embed=embed)
        except Exception as e:
            logger.error("通知送信失敗", error=str(e))

    def _build_content(self, request: ApprovalRequest) -> str:
        product = request.product
        plan = request.plan
        if not product or not plan:
            return "承認依頼"

        lines = [
            f"**📺 PR動画 承認依頼** `{request.request_id}`",
            f"修正回数: {request.revision_count}/{self.settings.max_revision_count}",
            "",
            f"**商品**: {product.display_title}",
            f"**カテゴリ**: {product.category}  /  **価格**: ¥{product.price:,}",
            f"**評価**: {product.rating} ({product.review_count}件)",
            f"**選定スコア**: {round(product.score, 3)}",
            "",
            "**キャプション案**:",
            f"```{plan.caption}```",
            "**ハッシュタグ**: " + " ".join(plan.hashtags),
            "",
            f"**動画**: {request.video_url}",
            "",
            f"{EMOJI_APPROVE} 承認  /  {EMOJI_REVISION} 修正(リプライで指示)  /  {EMOJI_REJECT} 却下",
        ]
        return "\n".join(lines)

    def _build_embed(self, request: ApprovalRequest) -> Any:
        try:
            import discord
        except ImportError:
            return None
        product = request.product
        if not product:
            return None
        embed = discord.Embed(
            title=product.display_title,
            description=product.description[:200],
            url=product.affiliate_url,
            color=0x00BFFF,
        )
        embed.add_field(name="ソース", value=product.source.upper(), inline=True)
        embed.add_field(name="価格", value=f"¥{product.price:,}", inline=True)
        embed.add_field(name="スコア", value=f"{round(product.score, 3)}", inline=True)
        if product.image_urls:
            embed.set_thumbnail(url=product.image_urls[0])
        return embed

    async def _handle_reaction(self, reaction: Any, user: Any) -> None:
        message_id = reaction.message.id
        request_id = self._message_requests.get(message_id)
        if not request_id:
            return

        if (
            self.settings.discord_owner_user_id
            and str(user.id) != str(self.settings.discord_owner_user_id)
        ):
            logger.info(
                "オーナー以外のリアクション無視",
                user_id=str(user.id),
                expected=self.settings.discord_owner_user_id,
            )
            return

        emoji = str(reaction.emoji)
        if emoji == EMOJI_APPROVE:
            await self.queue.resolve(
                request_id,
                ApprovalDecision(
                    request_id=request_id,
                    decision="approved",
                    approved_by=str(user.id),
                ),
            )
            await reaction.message.add_reaction("👍")
        elif emoji == EMOJI_REJECT:
            await self.queue.resolve(
                request_id,
                ApprovalDecision(
                    request_id=request_id,
                    decision="rejected",
                    approved_by=str(user.id),
                    feedback="ViFight により却下",
                ),
            )
            await reaction.message.add_reaction("🚫")
        elif emoji == EMOJI_REVISION:
            self._revision_waiting[request_id] = "waiting"
            await reaction.message.reply(
                "✏️ 修正指示を入力してください(このメッセージへの返信)"
            )

    async def _handle_message(self, message: Any) -> None:
        """修正指示メッセージの処理"""
        if not self._revision_waiting:
            return
        # 親メッセージ(承認依頼)へのリプライかチェック
        if not message.reference or not message.reference.message_id:
            return

        # 親メッセージ ID から request_id を逆引き
        # 修正催促 reply は bot 自身のメッセージなので、その親を辿る
        ref_id = message.reference.message_id
        request_id = self._message_requests.get(ref_id)
        if not request_id:
            # 1段親 (Bot のリマインダ) かもしれない
            try:
                ref_msg = await message.channel.fetch_message(ref_id)
                if ref_msg.reference:
                    parent_id = ref_msg.reference.message_id
                    request_id = self._message_requests.get(parent_id)
            except Exception:
                return

        if not request_id or request_id not in self._revision_waiting:
            return

        if (
            self.settings.discord_owner_user_id
            and str(message.author.id) != str(self.settings.discord_owner_user_id)
        ):
            return

        feedback = message.content.strip()
        if not feedback:
            return

        self._revision_waiting.pop(request_id, None)
        await self.queue.resolve(
            request_id,
            ApprovalDecision(
                request_id=request_id,
                decision="revision",
                feedback=feedback,
                approved_by=str(message.author.id),
            ),
        )
        await message.add_reaction("📝")
