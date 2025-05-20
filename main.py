import re
import json
import os
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.platform import AstrBotMessage
from astrbot.api.message_components import Plain

@register("delete_and_block_filter", "enixi", "词语删除与拦截器。可管理LLM回复的屏蔽词。输入 /过滤配置 查看当前配置。", "1.4.0")
class CustomWordFilter(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.plugin_id = "delete_and_block_filter"
        self.config = config
        self.config_file_path = os.path.join("data", "config", f"{self.plugin_id}_config.json")

        logger.info(f"[{self.plugin_id}] Plugin loaded (v1.4.0).")
        try:
            self._reload_config_from_self_dot_config(is_init_load=True)
        except Exception as e_init_reload:
            logger.error(f"[{self.plugin_id}] ERROR during initial config load in __init__: {e_init_reload}", exc_info=True)

    def _save_plugin_config(self):
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.config_file_path), exist_ok=True)
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            logger.info(f"[{self.plugin_id}] Configuration saved to {self.config_file_path}")
        except Exception as e:
            logger.error(f"[{self.plugin_id}] Failed to save configuration: {e}", exc_info=True)

    def _reload_config_from_self_dot_config(self, is_init_load: bool = False):
        """Loads configuration from self.config into class attributes. Optionally logs status."""
        
        self.config.setdefault('enable_delete_filter', False)
        self.config.setdefault('delete_words_list', [])
        self.config.setdefault('delete_case_sensitive', False)
        self.config.setdefault('delete_match_whole_word', True)
        self.config.setdefault('enable_block_filter', False)
        self.config.setdefault('block_words_list', [])
        self.config.setdefault('block_case_sensitive', False)
        self.config.setdefault('block_match_whole_word', True)
        self.config.setdefault('block_response_message', '')

        enable_delete_val = self.config.get('enable_delete_filter')
        if isinstance(enable_delete_val, str):
            self.enable_delete_filter = enable_delete_val.lower() == 'true'
        elif isinstance(enable_delete_val, bool):
            self.enable_delete_filter = enable_delete_val
        else:
            self.enable_delete_filter = False

        self.delete_words_list = self.config.get('delete_words_list', [])
        self.delete_case_sensitive = self.config.get('delete_case_sensitive', False)
        self.delete_match_whole_word = self.config.get('delete_match_whole_word', True)

        enable_block_val = self.config.get('enable_block_filter')
        if isinstance(enable_block_val, str):
            self.enable_block_filter = enable_block_val.lower() == 'true'
        elif isinstance(enable_block_val, bool):
            self.enable_block_filter = enable_block_val
        else:
            self.enable_block_filter = False
        
        self.block_words_list = self.config.get('block_words_list', [])
        self.block_case_sensitive = self.config.get('block_case_sensitive', False)
        self.block_match_whole_word = self.config.get('block_match_whole_word', True)
        self.block_response_message = self.config.get('block_response_message', '')

        if not is_init_load:
            logger.info(f"Plugin [{self.plugin_id}] config reloaded by command.")
            if self.enable_delete_filter:
                logger.info(f"  - Delete filter: ENABLED. Words: {len(self.delete_words_list)}, WholeWord: {self.delete_match_whole_word}, CaseSensitive: {self.delete_case_sensitive}")
            else: 
                logger.info(f"  - Delete filter: DISABLED")
            
            if self.enable_block_filter:
                block_action = f"Response: '{self.block_response_message}'" if self.block_response_message else "Action: [Clear Message]"
                logger.info(f"  - Block filter: ENABLED. Words: {len(self.block_words_list)}, WholeWord: {self.block_match_whole_word}, CaseSensitive: {self.block_case_sensitive}, {block_action}")
            else: 
                logger.info(f"  - Block filter: DISABLED")

    def _build_regex(self, words: list, case_sensitive: bool, match_whole_word: bool) -> tuple[str, int]:
        if not words:
            return "", 0
        processed_words = [re.escape(str(word)) for word in words] # Ensure words are strings
        pattern = "|".join(processed_words)
        if match_whole_word:
            pattern = r"\b(?:" + pattern + r")\b"
        
        flags = 0 if case_sensitive else re.IGNORECASE
        return pattern, flags

    @filter.on_llm_response()
    async def filter_llm_response(self, event: AstrMessageEvent, response: LLMResponse):
        if response is None or not hasattr(response, 'completion_text') or response.completion_text is None:
            return

        original_text = response.completion_text
        modified_text = original_text
        action_taken = False

        if self.enable_block_filter and self.block_words_list:
            block_pattern, block_flags = self._build_regex(self.block_words_list, self.block_case_sensitive, self.block_match_whole_word)
            if block_pattern:
                try:
                    if re.search(block_pattern, modified_text, block_flags):
                        action_taken = True
                        original_before_block = modified_text
                        if self.block_response_message:
                            modified_text = self.block_response_message
                            logger.info(f"[{self.plugin_id}] Blocked: Text replaced. Original: '{original_before_block}' -> New: '{modified_text}'")
                        else:
                            modified_text = ""
                            logger.info(f"[{self.plugin_id}] Blocked: Text cleared. Original: '{original_before_block}'")
                        response.completion_text = modified_text
                        return 
                except re.error as e: 
                    logger.error(f"[{self.plugin_id}] Block regex error for pattern '{block_pattern}': {e}", exc_info=True)

        if self.enable_delete_filter and self.delete_words_list:
            delete_pattern, delete_flags = self._build_regex(self.delete_words_list, self.delete_case_sensitive, self.delete_match_whole_word)
            if delete_pattern:
                try:
                    text_before_delete = modified_text
                    modified_text = re.sub(delete_pattern, "", text_before_delete, flags=delete_flags)
                    if modified_text != text_before_delete:
                        action_taken = True
                        logger.info(f"[{self.plugin_id}] Deleted: Text modified. Before: '{text_before_delete}' -> After: '{modified_text}'")
                except re.error as e: 
                    logger.error(f"[{self.plugin_id}] Delete regex error for pattern '{delete_pattern}': {e}", exc_info=True)
        
        if action_taken:
            response.completion_text = modified_text

    # --- Chat Command Handlers ---

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("加删除词")
    async def cmd_add_delete_word(self, event: AstrMessageEvent, *, item: str):
        """[Admin] 添加一个词到删除列表。用法: /加删除词 <要删除的词或符号>"""
        if not event.is_admin():
            yield event.plain_result("抱歉，您没有权限使用此命令。")
            return
        if not item:
            yield event.plain_result("请提供要添加的词语/符号。用法: /加删除词 <内容>")
            return
        
        current_list = self.config.get('delete_words_list', [])
        if item not in current_list:
            current_list.append(item)
            self.config['delete_words_list'] = current_list
            self._save_plugin_config()
            self._reload_config_from_self_dot_config()
            yield event.plain_result(f"已添加 '{item}' 到删除列表。")
        else:
            yield event.plain_result(f"'{item}' 已经在删除列表里了。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("减删除词")
    async def cmd_remove_delete_word(self, event: AstrMessageEvent, *, item: str):
        """[Admin] 从删除列表移除一个词。用法: /减删除词 <要移除的词或符号>"""
        if not event.is_admin():
            yield event.plain_result("抱歉，您没有权限使用此命令。")
            return
        if not item:
            yield event.plain_result("请提供要移除的词语/符号。用法: /减删除词 <内容>")
            return

        current_list = self.config.get('delete_words_list', [])
        if item in current_list:
            current_list.remove(item)
            self.config['delete_words_list'] = current_list
            self._save_plugin_config()
            self._reload_config_from_self_dot_config()
            yield event.plain_result(f"已从删除列表移除 '{item}'。")
        else:
            yield event.plain_result(f"'{item}' 不在删除列表里。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("加拦截词")
    async def cmd_add_block_word(self, event: AstrMessageEvent, *, item: str):
        """[Admin] 添加一个词到拦截列表。用法: /加拦截词 <要拦截的词或符号>"""
        if not event.is_admin():
            yield event.plain_result("抱歉，您没有权限使用此命令。")
            return
        if not item:
            yield event.plain_result("请提供要添加到拦截列表的词语/符号。用法: /加拦截词 <内容>")
            return

        current_list = self.config.get('block_words_list', [])
        if item not in current_list:
            current_list.append(item)
            self.config['block_words_list'] = current_list
            self._save_plugin_config()
            self._reload_config_from_self_dot_config()
            yield event.plain_result(f"已添加 '{item}' 到拦截列表。")
        else:
            yield event.plain_result(f"'{item}' 已经在拦截列表里了。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("减拦截词")
    async def cmd_remove_block_word(self, event: AstrMessageEvent, *, item: str):
        """[Admin] 从拦截列表移除一个词。用法: /减拦截词 <要移除的词或符号>"""
        if not event.is_admin():
            yield event.plain_result("抱歉，您没有权限使用此命令。")
            return
        if not item:
            yield event.plain_result("请提供要从拦截列表移除的词语/符号。用法: /减拦截词 <内容>")
            return

        current_list = self.config.get('block_words_list', [])
        if item in current_list:
            current_list.remove(item)
            self.config['block_words_list'] = current_list
            self._save_plugin_config()
            self._reload_config_from_self_dot_config()
            yield event.plain_result(f"已从拦截列表移除 '{item}'。")
        else:
            yield event.plain_result(f"'{item}' 不在拦截列表里。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("切换删除")
    async def cmd_toggle_delete_filter(self, event: AstrMessageEvent):
        """[Admin] 开/关词语删除功能。"""
        if not event.is_admin():
            yield event.plain_result("抱歉，您没有权限使用此命令。")
            return
        current_status = self.config.get('enable_delete_filter', False)
        new_status = not current_status
        self.config['enable_delete_filter'] = new_status
        self._save_plugin_config()
        self._reload_config_from_self_dot_config()
        yield event.plain_result(f"词语删除功能已 {'开启' if new_status else '关闭'}。")

    @filter.command("切换拦截")
    async def cmd_toggle_block_filter(self, event: AstrMessageEvent):
        """[Admin] 开/关消息拦截功能。"""
        if not event.is_admin():
            yield event.plain_result("抱歉，您没有权限使用此命令。")
            return
        
        current_status = self.config.get('enable_block_filter', False)
        new_status = not current_status
        self.config['enable_block_filter'] = new_status
        self._save_plugin_config()
        self._reload_config_from_self_dot_config()
        yield event.plain_result(f"消息拦截功能已 {'开启' if new_status else '关闭'}。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("过滤配置", "词语过滤配置")
    async def cmd_show_filter_config(self, event: AstrMessageEvent):
        """[Admin] 显示当前所有过滤器配置及可用命令。"""
        if not event.is_admin():
            yield event.plain_result("抱歉，您没有权限使用此命令。")
            return
        self._reload_config_from_self_dot_config() 

        delete_enabled = "开启" if self.enable_delete_filter else "关闭"
        delete_list_str = ", ".join(f"'{w}'" for w in self.delete_words_list) if self.delete_words_list else "空"
        delete_case = "区分" if self.delete_case_sensitive else "不区分"
        delete_whole = "是" if self.delete_match_whole_word else "否"

        block_enabled = "开启" if self.enable_block_filter else "关闭"
        block_list_str = ", ".join(f"'{w}'" for w in self.block_words_list) if self.block_words_list else "空"
        block_case = "区分" if self.block_case_sensitive else "不区分"
        block_whole = "是" if self.block_match_whole_word else "否"
        block_resp = f"'{self.block_response_message}'" if self.block_response_message else "无 (清空消息)"

        reply_message = f"""--- 过滤器当前配置 ({self.plugin_id}) ---
删除功能: {delete_enabled}
  - 删除列表: {delete_list_str}
  - 大小写敏感: {delete_case}
  - 仅匹配整个词: {delete_whole}

拦截功能: {block_enabled}
  - 拦截列表: {block_list_str}
  - 大小写敏感: {block_case}
  - 仅匹配整个词: {block_whole}
  - 拦截后回复: {block_resp}

--- 可用管理命令 ---
  /加删除词 <词语>   - 添加词到删除列表
  /减删除词 <词语>   - 从删除列表移除词
  /切换删除          - 开/关删除功能

  /加拦截词 <词语>   - 添加词到拦截列表
  /减拦截词 <词语>   - 从拦截列表移除词
  /切换拦截          - 开/关拦截功能
  

-----------------------------------"""
        yield event.plain_result(reply_message)