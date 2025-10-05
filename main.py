import re
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from astrbot.api import logger

@register("astrbot_plugin_delete_and_block_filter", "enixi", "词语删除与拦截器 - 优夏专用版", "2.0.2-yx")
class CustomWordFilter(Star):
    # 定义要强制删除的格式的正则表达式
    # r'<thinking>.*?</thinking>' : 匹配 <thinking> 到 </thinking> 之间的所有内容（非贪婪）
    DELETE_PATTERNS = [
        r'<thinking>.*?</thinking>',
        r'<guifan>.*?</guifan>',
        r'<!--.*?-->'
    ]

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.plugin_id = "astrbot_plugin_delete_and_block_filter"
        
        # 从配置中获取总开关状态，默认为 True
        self.enable_filter = config.get("enable_filter", True)
        
        # 预编译正则表达式，提高效率
        self.regex_to_delete = re.compile("|".join(self.DELETE_PATTERNS), re.IGNORECASE | re.DOTALL)
        
        logger.info(f"[{self.plugin_id}] 插件已载入 (v2.0.2-yx) - 过滤器状态: {'开启' if self.enable_filter else '关闭'}")

    def _process_text(self, text: str) -> str:
        """
        通用文本处理函数：
        1. 删除所有预设的正则表达式匹配到的内容。
        2. 寻找 <content> 标签，并提取其后的内容。
        3. 清理最终结果首尾的空白字符（如空格、换行符）。
        """
        # 步骤 1: 使用预编译的正则进行替换
        processed_text = self.regex_to_delete.sub("", text)

        # 步骤 2: 查找并处理 <content> 标签
        content_tag = '<content>'
        tag_pos = processed_text.find(content_tag)
        if tag_pos != -1:
            # 如果找到，则提取 <content> 之后的所有内容
            processed_text = processed_text[tag_pos + len(content_tag):]

        # 步骤 3: 清理首尾的空白字符并返回
        return processed_text.strip()

    @filter.on_llm_response()
    async def filter_llm_response(self, event: AstrMessageEvent, response: LLMResponse):
        """过滤 LLM (AI) 的回复内容。"""
        if not self.enable_filter or not response or not hasattr(response, 'completion_text') or not response.completion_text:
            return

        original_text = str(response.completion_text)
        modified_text = self._process_text(original_text)
        
        if modified_text != original_text:
            response.completion_text = modified_text
            logger.debug(f"[{self.plugin_id}] LLM 过滤器已处理内容。")
            logger.debug(f"[{self.plugin_id}] 结果预览: {modified_text[:150]}...")

    @filter.on_decorating_result()
    async def filter_final_output(self, event: AstrMessageEvent):
        """过滤 Bot 最终输出的内容，确保最终发给用户的消息是干净的。"""
        if not self.enable_filter:
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
                
                # 只有当处理后仍有内容时，才添加到新的消息链中
                if modified_component_text:
                    new_chain.append(Plain(modified_component_text))
            else:
                # 保留非文本组件（如图片、按钮等）
                new_chain.append(component)
        
        if text_changed:
            if not new_chain:
                # 如果处理后所有文本内容都为空，则拦截该消息的发送
                event.set_result(MessageEventResult())
                logger.debug(f"[{self.plugin_id}] 最终输出过滤器处理后内容为空，已拦截该消息。")
            else:
                result.chain = new_chain
                logger.debug(f"[{self.plugin_id}] 最终输出过滤器已处理内容。")
