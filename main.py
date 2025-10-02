import re
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from astrbot.api import logger # 保留 logger 用于调试输出

@register("astrbot_plugin_delete_and_block_filter", "enixi", "词语删除与拦截器 - 极简版", "2.0.1-min")
class CustomWordFilter(Star):
    # 定义要强制删除的格式的正则表达式
    # r'<guifan>.*?</guifan>' : 匹配 <guifan> 到 </guifan> 之间的所有内容（非贪婪）
    # r'<!--.*?-->' : 匹配 <!-- 到 --> 之间的所有内容（非贪婪）
    DELETE_PATTERNS = [
        r'<guifan>.*?</guifan>',
        r'<!--.*?-->'
    ]

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.plugin_id = "astrbot_plugin_delete_and_block_filter"
        
        # 预编译正则表达式，使用 DOTALL 模式确保能匹配跨行的标签/注释内容
        self.regex_to_delete = re.compile("|".join(self.DELETE_PATTERNS), re.IGNORECASE | re.DOTALL)
        
        logger.info(f"[{self.plugin_id}] 插件已载入 (v2.0.1-min) - 强制删除 <guifan> 和 <!-- 结构")

    @filter.on_llm_response()
    async def filter_llm_response(self, event: AstrMessageEvent, response: LLMResponse):
        """
        过滤 LLM (AI) 的回复内容。
        无条件删除 <guifan>...</guifan> 和 <!--...--> 格式的内容。
        """
        if not response or not hasattr(response, 'completion_text') or not response.completion_text:
            return

        original_text = str(response.completion_text)
        
        # 使用预编译的正则进行替换，将匹配到的内容替换为空字符串
        modified_text = self.regex_to_delete.sub("", original_text)
        
        if modified_text != original_text:
            response.completion_text = modified_text
            logger.debug(f"[{self.plugin_id}] LLM 强制删除：原文长度 {len(original_text)} -> 结果长度 {len(modified_text)}")
            logger.debug(f"[{self.plugin_id}] 结果预览: {modified_text[:100]}...")


    @filter.on_decorating_result()
    async def filter_final_output(self, event: AstrMessageEvent):
        """
        过滤 Bot 最终输出的内容，包括错误消息。
        无条件删除 <guifan>...</guifan> 和 <!--...--> 格式的内容。
        """
        result = event.get_result()
        if not result or not hasattr(result, 'chain') or not result.chain:
            return

        text_changed = False
        new_chain = []
        
        for component in result.chain:
            if isinstance(component, Plain):
                original_component_text = str(component.text)
                
                # 使用预编译的正则进行替换
                modified_component_text = self.regex_to_delete.sub("", original_component_text)
                
                if modified_component_text != original_component_text:
                    text_changed = True
                
                # 如果内容不为空（避免留下空白消息），则加入新的消息链
                if modified_component_text.strip() or not original_component_text.strip():
                    new_chain.append(Plain(modified_component_text))
            else:
                # 保留非文本组件（如图片、按钮等）
                new_chain.append(component)
        
        if text_changed:
            result.chain = new_chain
            logger.debug(f"[{self.plugin_id}] 最终输出强制删除：内容已修改。")
