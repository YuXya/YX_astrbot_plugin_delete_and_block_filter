import re
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from astrbot.api import logger

@register("astrbot_plugin_delete_and_block_filter", "enixi", "词语删除与拦截器 - 优夏专用版", "2.0.3-yx")
class CustomWordFilter(Star):
    # 定义静态的、写死的正则表达式模式
    # 这些是复杂的、需要用正则语法匹配的模式
    HARDCODED_PATTERNS = [
        r'<thinking>.*?</thinking>', # 匹配 <thinking> 到 </thinking> 之间的所有内容（非贪婪）
        r'<guifan>.*?</guifan>',
        r'<!--.*?-->'
    ]

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.plugin_id = "astrbot_plugin_delete_and_block_filter"
        
        # 从配置中获取总开关状态
        self.enable_filter = config.get("enable_filter", True)
        
        # 从配置中获取用户自定义的、需要作为普通文本删除的标签列表
        custom_tags = config.get("custom_delete_tags", ["<content>", "</content>"])
        
        # 将用户自定义的普通文本标签进行转义，使其能安全地在正则表达式中使用
        user_patterns = [re.escape(tag) for tag in custom_tags if tag]
        
        # 合并写死的正则模式和用户自定义的模式
        all_patterns = self.HARDCODED_PATTERNS + user_patterns
        
        # 预编译所有正则表达式，提高效率
        # 使用 try-except 避免无效的正则表达式导致插件崩溃
        try:
            self.regex_to_delete = re.compile("|".join(all_patterns), re.IGNORECASE | re.DOTALL)
        except re.error as e:
            logger.error(f"[{self.plugin_id}] 正则表达式编译失败: {e}。过滤器将不会生效。")
            self.regex_to_delete = None # 编译失败则禁用正则功能
        
        logger.info(f"[{self.plugin_id}] 插件已载入 (v2.0.3-yx) - 过滤器状态: {'开启' if self.enable_filter else '关闭'}")
        if self.enable_filter and self.regex_to_delete:
            logger.debug(f"[{self.plugin_id}] 当前加载的过滤规则数量: {len(all_patterns)}")

    def _process_text(self, text: str) -> str:
        """
        通用文本处理函数：
        1. 使用预编译的正则表达式删除所有匹配到的内容。
        2. 清理最终结果首尾的空白字符（如空格、换行符）。
        """
        if not self.regex_to_delete or not text:
            return text
        
        # 使用合并后的正则进行替换
        processed_text = self.regex_to_delete.sub("", text)

        # 清理首尾的空白字符并返回
        return processed_text.strip()

    @filter.on_llm_response()
    async def filter_llm_response(self, event: AstrMessageEvent, response: LLMResponse):
        """过滤 LLM (AI) 的回复内容。"""
        if not self.enable_filter or not self.regex_to_delete or not response or not hasattr(response, 'completion_text') or not response.completion_text:
            return

        original_text = str(response.completion_text)
        modified_text = self._process_text(original_text)
        
        if modified_text != original_text:
            response.completion_text = modified_text
            logger.debug(f"[{self.plugin_id}] LLM 过滤器已处理内容。")

    @filter.on_decorating_result()
    async def filter_final_output(self, event: AstrMessageEvent):
        """过滤 Bot 最终输出的内容，确保最终发给用户的消息是干净的。"""
        if not self.enable_filter or not self.regex_to_delete:
            return

        result = event.get_result()
        if not result or not hasattr(result, 'chain') or not result.chain:
            return

        text_changed = False
        new_chain = []
        
        for component in result.chain:
            if isinstance(component, Plain):
                original_component_text = str(component.text)
                modified_component_text = self._process_text(original_component_text)
                
                if modified_component_text != original_component_text:
                    text_changed = True
                
                if modified_component_text:
                    new_chain.append(Plain(modified_component_text))
            else:
                new_chain.append(component)
        
        if text_changed:
            if not new_chain:
                event.set_result(MessageEventResult())
                logger.debug(f"[{self.plugin_id}] 最终输出过滤器处理后内容为空，已拦截该消息。")
            else:
                result.chain = new_chain
                logger.debug(f"[{self.plugin_id}] 最终输出过滤器已处理内容。")

