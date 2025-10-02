import re
import json
import os
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.platform import AstrBotMessage
from astrbot.api.message_components import Plain

@register("astrbot_plugin_delete_and_block_filter", "enixi", "词语删除与拦截器。可管理LLM回复及Bot最终输出的屏蔽词。输入 /过滤配置 查看当前配置。", "2.0.0")
class CustomWordFilter(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.plugin_id = "astrbot_plugin_delete_and_block_filter"
        self.config = config
        
        # 定义硬编码的强制删除模式（无视用户配置，始终删除）
        self.HARDCODED_DELETE_PATTERNS = [
            r'<guifan>.*?</guifan>',  # 强制删除所有 <guifan>...</guifan> 标签内容（非贪婪匹配）
            r'<!--.*?-->'          # 强制删除所有 <!--...--> 注释内容（非贪婪匹配）
        ]
        
        # 获取插件数据目录（按照AstrBot推荐方式）
        try:
            from astrbot.api.star import StarTools
            self.data_dir = StarTools.get_data_dir(self.plugin_id)
        except ImportError:
            # 兼容旧版本
            self.data_dir = None

        logger.info(f"[{self.plugin_id}] 插件已载入 (v2.0.0)")
        try:
            self._reload_config()
        except Exception as e:
            logger.error(f"[{self.plugin_id}] 配置加载失败: {e}", exc_info=True)

    def _save_config(self):
        """保存配置"""
        try:
            self.config.save_config()
            logger.info(f"[{self.plugin_id}] 配置已保存")
        except Exception as e:
            logger.error(f"[{self.plugin_id}] 保存配置失败: {e}", exc_info=True)

    def _reload_config(self):
        """加载配置到类属性"""
        
        # 调试配置
        self.config.setdefault('show_console_log', True)
        
        # LLM回复过滤器配置
        self.config.setdefault('enable_llm_filter', False)
        self.config.setdefault('llm_delete_words', [])
        self.config.setdefault('llm_delete_case_sensitive', False)
        self.config.setdefault('llm_delete_match_whole_word', False)
        self.config.setdefault('llm_block_words', [])
        self.config.setdefault('llm_block_case_sensitive', False)
        self.config.setdefault('llm_block_match_whole_word', False)
        self.config.setdefault('llm_block_response', '')

        # 总输出过滤器配置
        self.config.setdefault('enable_final_filter', False)
        self.config.setdefault('final_delete_words', [])
        self.config.setdefault('final_delete_case_sensitive', False)
        self.config.setdefault('final_delete_match_whole_word', False)
        self.config.setdefault('final_block_words', [])
        self.config.setdefault('final_block_case_sensitive', False)
        self.config.setdefault('final_block_match_whole_word', False)
        self.config.setdefault('final_block_response', '')

        # 加载到实例变量
        self.show_console_log = self.config.get('show_console_log', True)
        
        self.enable_llm_filter = self.config.get('enable_llm_filter', False)
        self.llm_delete_words = self.config.get('llm_delete_words', [])
        self.llm_delete_case_sensitive = self.config.get('llm_delete_case_sensitive', False)
        self.llm_delete_match_whole_word = self.config.get('llm_delete_match_whole_word', False)
        self.llm_block_words = self.config.get('llm_block_words', [])
        self.llm_block_case_sensitive = self.config.get('llm_block_case_sensitive', False)
        self.llm_block_match_whole_word = self.config.get('llm_block_match_whole_word', False)
        self.llm_block_response = self.config.get('llm_block_response', '')

        self.enable_final_filter = self.config.get('enable_final_filter', False)
        self.final_delete_words = self.config.get('final_delete_words', [])
        self.final_delete_case_sensitive = self.config.get('final_delete_case_sensitive', False)
        self.final_delete_match_whole_word = self.config.get('final_delete_match_whole_word', False)
        self.final_block_words = self.config.get('final_block_words', [])
        self.final_block_case_sensitive = self.config.get('final_block_case_sensitive', False)
        self.final_block_match_whole_word = self.config.get('final_block_match_whole_word', False)
        self.final_block_response = self.config.get('final_block_response', '')

        logger.info(f"[{self.plugin_id}] 配置已重载")

    def _build_regex(self, words: list, case_sensitive: bool = False, match_whole_word: bool = False) -> str:
        """构建正则表达式，支持特殊模式和硬编码删除"""
        patterns = []
        
        # 1. 处理用户配置中的词语
        for word in words:
            word_str = str(word).strip()
            if not word_str:
                continue
                
            # 检查是否是特殊模式（如 &&...&&）
            if self._is_special_pattern(word_str):
                # 处理特殊模式
                pattern = self._convert_special_pattern(word_str)
                patterns.append(pattern)
            else:
                # 处理普通词语
                escaped_word = re.escape(word_str)
                if match_whole_word:
                    escaped_word = r'\b' + escaped_word + r'\b'
                patterns.append(escaped_word)
        
        # 2. 【硬编码删除】无视配置，强制删除的模式
        # 这一步保证了 <guifan>...</guifan> 和 <!--...--> 始终被删除
        patterns.extend(self.HARDCODED_DELETE_PATTERNS) 
            
        if not patterns:
            return ""
            
        return "|".join(patterns)

    def _is_special_pattern(self, word: str) -> bool:
        """检查是否是特殊模式 (仅检查动态配置支持的特殊字符组合)"""
        # 检查是否包含特殊字符组合
        special_chars = ['&&', '**', '##', '@@', '%%', '$$']
        for chars in special_chars:
            if chars in word:
                return True
        return False

    def _convert_special_pattern(self, word: str) -> str:
        """将特殊模式转换为正则表达式 (仅转换动态配置支持的特殊字符组合)"""
        
        # 处理 &&...&& 模式
        if '&&' in word:
            # 如果是 &&具体内容&&，就精确匹配
            # 如果是 &&&&（空内容），就匹配任意 &&...&& 格式
            if word == '&&&&':
                return r'&&[^&]*&&'
            else:
                # 精确匹配指定内容
                return re.escape(word)
        
        # 处理其他特殊字符模式
        special_patterns = {
            '**': r'\*\*[^*]*\*\*',
            '##': r'##[^#]*##',
            '@@': r'@@[^@]*@@',
            '%%': r'%%[^%]*%%',
            '$$': r'\$\$[^$]*\$\$'
        }
        
        for chars, pattern in special_patterns.items():
            if chars in word:
                if word == chars + chars:  # 如果是 ****（空内容）
                    return pattern
                else:
                    # 精确匹配指定内容
                    return re.escape(word)
        
        return re.escape(word)

    def _clean_special_chars(self, text: str) -> str:
        """清理特殊字符，如 &&shy&&、&&nbsp&& 等"""
        if not text:
            return text
        
        # 匹配 &&...&& 格式的特殊字符
        # 这个正则会匹配 && 开头和结尾，中间包含任意非&字符的模式
        # [^&]* 表示匹配任意数量的非&字符
        pattern = r'&&[^&]*&&'
        cleaned_text = re.sub(pattern, '', text)
        
        return cleaned_text

    @filter.on_llm_response()
    async def filter_llm_response(self, event: AstrMessageEvent, response: LLMResponse):
        """过滤LLM回复"""
        if not self.enable_llm_filter or not response or not hasattr(response, 'completion_text') or not response.completion_text:
            return

        original_text = str(response.completion_text)
        modified_text = original_text
        triggered_actions = []  # 记录触发的操作
        
        # 拦截功能（优先）
        if self.llm_block_words:
            pattern = self._build_regex(self.llm_block_words, self.llm_block_case_sensitive, self.llm_block_match_whole_word)
            flags = 0 if self.llm_block_case_sensitive else re.IGNORECASE
            if pattern and re.search(pattern, modified_text, flags):
                # 找出具体触发的词
                triggered_words = [word for word in self.llm_block_words 
                                 if re.search(self._build_regex([word], self.llm_block_case_sensitive, self.llm_block_match_whole_word), modified_text, flags)]
                
                if self.llm_block_response:
                    modified_text = self.llm_block_response
                    triggered_actions.append(f"拦截并替换(触发词: {triggered_words}) -> '{self.llm_block_response}'")
                else:
                    modified_text = ""
                    triggered_actions.append(f"拦截并清空(触发词: {triggered_words})")
                
                response.completion_text = modified_text
                
                # 输出合并的日志
                if self.show_console_log and triggered_actions:
                    logger.info(f"[{self.plugin_id}] LLM过滤结果: {' | '.join(triggered_actions)}")
                    logger.info(f"[{self.plugin_id}] 原文: '{original_text}'")
                
                return

        # 删除功能（硬编码和配置词语）
        # 即使 self.llm_delete_words 为空，_build_regex 也会返回包含硬编码删除模式的 pattern
        delete_patterns = self.llm_delete_words + ['<guifan>', '<!--'] # 仅用于日志追踪，实际删除已硬编码在 _build_regex 中
        
        pattern = self._build_regex(self.llm_delete_words, self.llm_delete_case_sensitive, self.llm_delete_match_whole_word)
        flags = 0 if self.llm_delete_case_sensitive else re.IGNORECASE
        
        if pattern:
            new_text = re.sub(pattern, "", modified_text, flags=flags)
            if new_text != modified_text:
                # 找出具体删除的词/模式（仅用于日志，不影响删除操作）
                triggered_words = []
                
                # 检查动态配置词语
                for word in self.llm_delete_words:
                    word_pattern = self._build_regex([word], self.llm_delete_case_sensitive, self.llm_delete_match_whole_word)
                    if re.search(word_pattern, modified_text, flags):
                        triggered_words.append(word)

                # 检查硬编码模式是否触发
                if re.search(r'<guifan>.*?</guifan>', modified_text, flags):
                    if '<guifan>' not in triggered_words: triggered_words.append('<guifan>...</guifan>')
                if re.search(r'<!--.*?-->', modified_text, flags):
                    if '<!--' not in triggered_words: triggered_words.append('<!--...-->')
                
                triggered_actions.append(f"删除敏感词/格式(触发: {triggered_words})")
                response.completion_text = new_text
                modified_text = new_text  # 更新修改后的文本
        
        # 输出合并的日志（只在有操作时输出）
        if self.show_console_log and triggered_actions:
            logger.info(f"[{self.plugin_id}] LLM过滤结果: {' | '.join(triggered_actions)}")
            logger.info(f"[{self.plugin_id}] 原文: '{original_text}'")
            # 如果有修改才显示结果
            if modified_text != original_text:
                logger.info(f"[{self.plugin_id}] 结果: '{modified_text}'")

    def _get_text_from_result(self, result: MessageEventResult) -> str:
        """从MessageEventResult提取文本"""
        if not result or not hasattr(result, 'chain') or not result.chain:
            return ""
        
        text_parts = []
        for component in result.chain:
            if isinstance(component, Plain):
                text_parts.append(str(component.text))
        
        return "".join(text_parts)

    @filter.on_decorating_result()
    async def filter_final_output(self, event: AstrMessageEvent):
        """过滤AstrBot最终输出（包括错误消息）"""
        if not self.enable_final_filter:
            return

        result = event.get_result()
        if not result or not hasattr(result, 'chain') or not result.chain:
            return

        original_text = self._get_text_from_result(result)
        if not original_text:
            return

        triggered_actions = []  # 记录触发的操作

        # 拦截功能（优先）
        if self.final_block_words:
            pattern = self._build_regex(self.final_block_words, self.final_block_case_sensitive, self.final_block_match_whole_word)
            flags = 0 if self.final_block_case_sensitive else re.IGNORECASE
            if pattern and re.search(pattern, original_text, flags):
                # 找出具体触发的词
                triggered_words = []
                for word in self.final_block_words:
                    word_pattern = self._build_regex([word], self.final_block_case_sensitive, self.final_block_match_whole_word)
                    if re.search(word_pattern, original_text, flags):
                        triggered_words.append(word)
                
                if self.final_block_response:
                    # 替换为自定义回复
                    result.chain = [Plain(self.final_block_response)]
                    triggered_actions.append(f"拦截并替换(触发词: {triggered_words}) -> '{self.final_block_response}'")
                else:
                    # 完全隐藏消息
                    event.stop_event()  # 阻止事件继续传播
                    event.set_result(None)  # 清除结果
                    triggered_actions.append(f"拦截并完全隐藏(触发词: {triggered_words})")
                
                # 输出合并的日志
                if self.show_console_log and triggered_actions:
                    logger.info(f"[{self.plugin_id}] 最终输出过滤结果: {' | '.join(triggered_actions)}")
                    logger.info(f"[{self.plugin_id}] 原文: '{original_text}'")
                
                return

        # 删除功能（硬编码和配置词语）
        pattern = self._build_regex(self.final_delete_words, self.final_delete_case_sensitive, self.final_delete_match_whole_word)
        flags = 0 if self.final_delete_case_sensitive else re.IGNORECASE
        if pattern:
            new_chain = []
            text_changed = False
            
            for component in result.chain:
                if isinstance(component, Plain):
                    original_component_text = str(component.text)
                    modified_component_text = re.sub(pattern, "", original_component_text, flags=flags)
                    
                    if modified_component_text != original_component_text:
                        text_changed = True
                    
                    if modified_component_text.strip():
                        new_chain.append(Plain(modified_component_text))
                else:
                    new_chain.append(component)
            
            if text_changed:
                # 找出具体删除的词/模式（仅用于日志，不影响删除操作）
                triggered_words = []
                
                # 检查动态配置词语
                for word in self.final_delete_words:
                    word_pattern = self._build_regex([word], self.final_delete_case_sensitive, self.final_delete_match_whole_word)
                    if re.search(word_pattern, original_text, flags):
                        triggered_words.append(word)

                # 检查硬编码模式是否触发
                if re.search(r'<guifan>.*?</guifan>', original_text, flags):
                    if '<guifan>...</guifan>' not in triggered_words: triggered_words.append('<guifan>...</guifan>')
                if re.search(r'<!--.*?-->', original_text, flags):
                    if '<!--...-->' not in triggered_words: triggered_words.append('<!--...-->')
                
                triggered_actions.append(f"删除敏感词/格式(触发: {triggered_words})")
                result.chain = new_chain
        
        # 输出合并的日志（只在有操作时输出）
        if self.show_console_log and triggered_actions:
            final_text = self._get_text_from_result(result)
            logger.info(f"[{self.plugin_id}] 最终输出过滤结果: {' | '.join(triggered_actions)}")
            logger.info(f"[{self.plugin_id}] 原文: '{original_text}'")
            
            if final_text != original_text:
                logger.info(f"[{self.plugin_id}] 结果: '{final_text}'")

    # === 配置命令 ===
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("过滤配置")
    async def cmd_show_config(self, event: AstrMessageEvent):
        """显示过滤器配置"""
        if not event.is_admin(): 
            yield event.plain_result("抱歉，您没有权限。")
            return
        
        self._reload_config()
        
        llm_status = "开启" if self.enable_llm_filter else "关闭"
        final_status = "开启" if self.enable_final_filter else "关闭"
        
        config_text = f"""=== 过滤器配置 ({self.plugin_id} v2.0.0) ===

🔧 调试设置:
  • 控制台详细日志: {'开启' if self.show_console_log else '关闭'}

🤖 LLM回复过滤器: {llm_status}
  • 删除词: {self.llm_delete_words if self.llm_delete_words else '无'}
    - 区分大小写: {'是' if self.llm_delete_case_sensitive else '否'}
    - 完全匹配: {'是' if self.llm_delete_match_whole_word else '否 (推荐)'}
    - 支持特殊模式: 如 &&123&& 删除所有 &&...&& 格式
  • 拦截词: {self.llm_block_words if self.llm_block_words else '无'}
    - 区分大小写: {'是' if self.llm_block_case_sensitive else '否'}
    - 完全匹配: {'是' if self.llm_block_match_whole_word else '否 (推荐)'}
  • 拦截回复: {f"'{self.llm_block_response}'" if self.llm_block_response else '留空(直接清空)'}

🛡️ 最终输出过滤器: {final_status}
  • 删除词: {self.final_delete_words if self.final_delete_words else '无'}
    - 区分大小写: {'是' if self.final_delete_case_sensitive else '否'}
    - 完全匹配: {'是' if self.final_delete_match_whole_word else '否 (推荐)'}
    - 支持特殊模式: 如 &&123&& 删除所有 &&...&& 格式
  • 拦截词: {self.final_block_words if self.final_block_words else '无'}
    - 区分大小写: {'是' if self.final_block_case_sensitive else '否'}
    - 完全匹配: {'是' if self.final_block_match_whole_word else '否 (推荐)'}
  • 拦截回复: {f"'{self.final_block_response}'" if self.final_block_response else '留空(直接隐藏)'}

=== 🚀 一键设置（推荐） ===
发送: /一键设置错误过滤

=== 📝 手动设置错误消息过滤 ===
1. /开启总输出过滤
2. /加总输出拦截词 请求失败
3. /加总输出拦截词 错误类型  
4. /加总输出拦截词 错误信息

=== 🎯 特殊模式使用说明 ===
删除词支持特殊模式，可以删除特定格式的内容：
• 普通词语: 输入 '鱼' 删除所有 '鱼' 字
• 强制删除格式 (始终启用，无需配置):
  • <guifan>...</guifan> 结构
  • <!--...--> 注释结构
• 可配置的特殊格式: 输入 '&&123&&' 删除所有 &&...&& 格式内容
• 支持格式: &&...&&, **...**, ##...##, @@...@@, %%...%%, $$...$$

=== 所有管理命令 ===
开关控制:
  /开启LLM过滤   /关闭LLM过滤
  /开启总输出过滤 /关闭总输出过滤
  /开启控制台日志 /关闭控制台日志

LLM回复管理:
  /加LLM删除词 <词语>  /减LLM删除词 <词语>
  /加LLM拦截词 <词语>  /减LLM拦截词 <词语>
  /设置LLM拦截回复 <内容>

最终输出管理:
  /加总输出删除词 <词语>  /减总输出删除词 <词语>
  /加总输出拦截词 <词语>  /减总输出拦截词 <词语>
  /设置总输出拦截回复 <内容>

测试功能:
  /测试删除词 <测试文本>

💡 高级配置请在网页管理界面调整区分大小写和完全匹配选项"""

        yield event.plain_result(config_text)

    # === 开关控制 ===
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("开启LLM过滤")
    async def cmd_enable_llm_filter(self, event: AstrMessageEvent):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        self.config['enable_llm_filter'] = True
        self._save_config()
        self._reload_config()
        yield event.plain_result("✅ LLM回复过滤器已开启")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("关闭LLM过滤")
    async def cmd_disable_llm_filter(self, event: AstrMessageEvent):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        self.config['enable_llm_filter'] = False
        self._save_config()
        self._reload_config()
        yield event.plain_result("❌ LLM回复过滤器已关闭")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("开启总输出过滤")
    async def cmd_enable_final_filter(self, event: AstrMessageEvent):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        self.config['enable_final_filter'] = True
        self._save_config()
        self._reload_config()
        yield event.plain_result("✅ 最终输出过滤器已开启")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("关闭总输出过滤")
    async def cmd_disable_final_filter(self, event: AstrMessageEvent):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        self.config['enable_final_filter'] = False
        self._save_config()
        self._reload_config()
        yield event.plain_result("❌ 最终输出过滤器已关闭")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("开启控制台日志")
    async def cmd_enable_console_log(self, event: AstrMessageEvent):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        self.config['show_console_log'] = True
        self._save_config()
        self._reload_config()
        yield event.plain_result("✅ 控制台详细日志已开启")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("关闭控制台日志")
    async def cmd_disable_console_log(self, event: AstrMessageEvent):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        self.config['show_console_log'] = False
        self._save_config()
        self._reload_config()
        yield event.plain_result("❌ 控制台详细日志已关闭")

    # === LLM回复管理 ===
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("加LLM删除词")
    async def cmd_add_llm_delete_word(self, event: AstrMessageEvent, *, word: str):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        if not word: yield event.plain_result("请提供要添加的词语"); return
        
        words = self.config.get('llm_delete_words', [])
        if word not in words:
            words.append(word)
            self.config['llm_delete_words'] = words
            self._save_config()
            self._reload_config()
            yield event.plain_result(f"✅ 已添加LLM删除词: '{word}'")
        else:
            yield event.plain_result(f"❗ '{word}' 已在LLM删除词列表中")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("减LLM删除词")
    async def cmd_remove_llm_delete_word(self, event: AstrMessageEvent, *, word: str):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        if not word: yield event.plain_result("请提供要移除的词语"); return
        
        words = self.config.get('llm_delete_words', [])
        if word in words:
            words.remove(word)
            self.config['llm_delete_words'] = words
            self._save_config()
            self._reload_config()
            yield event.plain_result(f"✅ 已移除LLM删除词: '{word}'")
        else:
            yield event.plain_result(f"❗ '{word}' 不在LLM删除词列表中")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("加LLM拦截词")
    async def cmd_add_llm_block_word(self, event: AstrMessageEvent, *, word: str):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        if not word: yield event.plain_result("请提供要添加的词语"); return
        
        words = self.config.get('llm_block_words', [])
        if word not in words:
            words.append(word)
            self.config['llm_block_words'] = words
            self._save_config()
            self._reload_config()
            yield event.plain_result(f"✅ 已添加LLM拦截词: '{word}'")
        else:
            yield event.plain_result(f"❗ '{word}' 已在LLM拦截词列表中")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("减LLM拦截词")
    async def cmd_remove_llm_block_word(self, event: AstrMessageEvent, *, word: str):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        if not word: yield event.plain_result("请提供要移除的词语"); return
        
        words = self.config.get('llm_block_words', [])
        if word in words:
            words.remove(word)
            self.config['llm_block_words'] = words
            self._save_config()
            self._reload_config()
            yield event.plain_result(f"✅ 已移除LLM拦截词: '{word}'")
        else:
            yield event.plain_result(f"❗ '{word}' 不在LLM拦截词列表中")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("设置LLM拦截回复")
    async def cmd_set_llm_block_response(self, event: AstrMessageEvent, *, response: str = ""):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        
        self.config['llm_block_response'] = response
        self._save_config()
        self._reload_config()
        
        if response:
            yield event.plain_result(f"✅ LLM拦截回复已设置为: '{response}'")
        else:
            yield event.plain_result("✅ LLM拦截回复已清空（将直接清空消息）")

    # === 最终输出管理 ===
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("加总输出删除词")
    async def cmd_add_final_delete_word(self, event: AstrMessageEvent, *, word: str):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        if not word: yield event.plain_result("请提供要添加的词语"); return
        
        words = self.config.get('final_delete_words', [])
        if word not in words:
            words.append(word)
            self.config['final_delete_words'] = words
            self._save_config()
            self._reload_config()
            yield event.plain_result(f"✅ 已添加总输出删除词: '{word}'")
        else:
            yield event.plain_result(f"❗ '{word}' 已在总输出删除词列表中")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("减总输出删除词")
    async def cmd_remove_final_delete_word(self, event: AstrMessageEvent, *, word: str):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        if not word: yield event.plain_result("请提供要移除的词语"); return
        
        words = self.config.get('final_delete_words', [])
        if word in words:
            words.remove(word)
            self.config['final_delete_words'] = words
            self._save_config()
            self._reload_config()
            yield event.plain_result(f"✅ 已移除总输出删除词: '{word}'")
        else:
            yield event.plain_result(f"❗ '{word}' 不在总输出删除词列表中")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("加总输出拦截词")
    async def cmd_add_final_block_word(self, event: AstrMessageEvent, *, word: str):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        if not word: yield event.plain_result("请提供要添加的词语"); return
        
        words = self.config.get('final_block_words', [])
        if word not in words:
            words.append(word)
            self.config['final_block_words'] = words
            self._save_config()
            self._reload_config()
            yield event.plain_result(f"✅ 已添加总输出拦截词: '{word}'")
        else:
            yield event.plain_result(f"❗ '{word}' 已在总输出拦截词列表中")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("减总输出拦截词")
    async def cmd_remove_final_block_word(self, event: AstrMessageEvent, *, word: str):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        if not word: yield event.plain_result("请提供要移除的词语"); return
        
        words = self.config.get('final_block_words', [])
        if word in words:
            words.remove(word)
            self.config['final_block_words'] = words
            self._save_config()
            self._reload_config()
            yield event.plain_result(f"✅ 已移除总输出拦截词: '{word}'")
        else:
            yield event.plain_result(f"❗ '{word}' 不在总输出拦截词列表中")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("设置总输出拦截回复")
    async def cmd_set_final_block_response(self, event: AstrMessageEvent, *, response: str = ""):
        if not event.is_admin(): yield event.plain_result("抱歉，您没有权限。"); return
        
        self.config['final_block_response'] = response
        self._save_config()
        self._reload_config()
        
        if response:
            yield event.plain_result(f"✅ 总输出拦截回复已设置为: '{response}'")
        else:
            yield event.plain_result("✅ 总输出拦截回复已清空（将直接清空消息）")

    # === 快捷配置命令 ===
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("一键设置错误过滤")
    async def cmd_quick_setup_error_filter(self, event: AstrMessageEvent):
        """一键设置错误消息过滤"""
        if not event.is_admin(): 
            yield event.plain_result("抱歉，您没有权限。")
            return
        
        # 自动开启过滤器
        self.config['enable_final_filter'] = True
        # 添加错误关键词
        error_keywords = ['请求失败', '错误类型', '错误信息', 'Exception', 'Error', 'Traceback']
        
        # 添加常见的错误关键词
        final_block_words = self.config.get('final_block_words', [])
        
        added_words = []
        for keyword in error_keywords:
            if keyword not in final_block_words:
                final_block_words.append(keyword)
                added_words.append(keyword)
        
        self.config['final_block_words'] = final_block_words
        
        # 清空拦截回复（直接隐藏错误消息）
        self.config['final_block_response'] = ''
        
        # 保存并重载配置
        self._save_config()
        self._reload_config()
        
        result_text = "✅ 错误消息过滤已一键设置完成！\n\n"
        result_text += "已开启: 🛡️ 最终输出过滤器\n"
        result_text += f"已添加拦截词: {added_words if added_words else '无新增（已存在）'}\n"
        result_text += "拦截方式: 直接隐藏错误消息\n\n"
        result_text += "现在用户将看不到API错误信息了！\n"
        result_text += "发送 /过滤配置 查看详细设置"
        
        yield event.plain_result(result_text)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("测试删除词")
    async def cmd_test_delete_word(self, event: AstrMessageEvent, *, test_text: str = ""):
        """测试删除词功能"""
        if not event.is_admin(): 
            yield event.plain_result("抱歉，您没有权限。")
            return
        
        if not test_text:
            yield event.plain_result("请提供测试文本，格式：/测试删除词 测试文本内容")
            return
        
        # 测试LLM删除词
        llm_result = test_text
        if self.llm_delete_words or self.HARDCODED_DELETE_PATTERNS:
            pattern = self._build_regex(self.llm_delete_words, self.llm_delete_case_sensitive, self.llm_delete_match_whole_word)
            flags = 0 if self.llm_delete_case_sensitive else re.IGNORECASE
            if pattern:
                llm_result = re.sub(pattern, "", test_text, flags=flags)
        
        # 测试最终输出删除词
        final_result = test_text
        if self.final_delete_words or self.HARDCODED_DELETE_PATTERNS:
            pattern = self._build_regex(self.final_delete_words, self.final_delete_case_sensitive, self.final_delete_match_whole_word)
            flags = 0 if self.final_delete_case_sensitive else re.IGNORECASE
            if pattern:
                final_result = re.sub(pattern, "", test_text, flags=flags)
        
        result_text = f"""=== 删除词测试结果 ===

📝 原始文本: '{test_text}'

🤖 LLM删除词处理:
  • 删除词列表: {self.llm_delete_words if self.llm_delete_words else '无'}
  • 强制删除格式: <guifan>...</guifan>, <!--...-->
  • 处理结果: '{llm_result}'
  • 是否改变: {'是' if llm_result != test_text else '否'}

🛡️ 最终输出删除词处理:
  • 删除词列表: {self.final_delete_words if self.final_delete_words else '无'}
  • 强制删除格式: <guifan>...</guifan>, <!--...-->
  • 处理结果: '{final_result}'
  • 是否改变: {'是' if final_result != test_text else '否'}

💡 特殊模式示例:
  • 添加删除词 '&&&&' 可删除所有 &&...&& 格式
  • 强制删除格式 <guifan>...</guifan> 和 <!--...--> 始终生效。"""
        
        yield event.plain_result(result_text)
