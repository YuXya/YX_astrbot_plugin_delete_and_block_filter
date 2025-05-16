import re
from astrbot.api.event import filter, AstrMessageEvent # AstrMessageEvent for the event type
from astrbot.api.provider import LLMResponse # LLMResponse for the response type
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
# AstrBotMessage might not be needed if we only modify completion_text
# from astrbot.api.platform import AstrBotMessage 

@register("delete_and_block_filter", "enixi", "过滤指定的单词/符号或屏蔽包含它们的消息.", "1.3.2") # Updated name, author, and version
class CustomWordFilter(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.plugin_id = "delete_and_block_filter" # Align with new ID
        self.config = config

        logger.info(f"[{self.plugin_id}] ====== INITIALIZING PLUGIN ({self.plugin_id} v1.3.2) ======")
        # logger.info(f"[{self.plugin_id}] RAW CONFIG RECEIVED IN __init__: {str(config)}") # Kept for initial deep debug if needed, then remove

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

        logger.info(f"插件 [{self.plugin_id}] 配置加载完毕。")
        if self.enable_delete_filter:
            logger.info(f"  - Delete filter: ENABLED. Words: {len(self.delete_words_list)}, WholeWord: {self.delete_match_whole_word}, CaseSensitive: {self.delete_case_sensitive}")
        else: logger.info(f"  - Delete filter: DISABLED")
        
        if self.enable_block_filter:
            block_action = f"Response: '{self.block_response_message}'" if self.block_response_message else "Action: [Clear Message]"
            logger.info(f"  - Block filter: ENABLED. Words: {len(self.block_words_list)}, WholeWord: {self.block_match_whole_word}, CaseSensitive: {self.block_case_sensitive}, {block_action}")
        else: logger.info(f"  - Block filter: DISABLED")
        logger.info(f"[{self.plugin_id}] ====== END PLUGIN INITIALIZATION ======")

    def _build_regex(self, words: list, case_sensitive: bool, match_whole_word: bool) -> tuple[str, int]:
        if not words:
            return "", 0 # Return tuple
        processed_words = [re.escape(word) for word in words]
        pattern = "|".join(processed_words)
        if match_whole_word:
            pattern = r"\b(?:" + pattern + r")\b" # Use non-capturing group for the whole pattern
        
        flags = 0 if case_sensitive else re.IGNORECASE
        return pattern, flags

    @filter.on_llm_response()
    async def filter_llm_response(self, event: AstrMessageEvent, response: LLMResponse):
        if response is None or not hasattr(response, 'completion_text') or response.completion_text is None:
            # logger.debug(f"[{self.plugin_id}] No completion_text in response. Skipping.") # Too verbose for info
            return

        original_text = response.completion_text
        modified_text = original_text
        action_taken = False

        # Block filter (priority)
        if self.enable_block_filter and self.block_words_list:
            block_pattern, block_flags = self._build_regex(self.block_words_list, self.block_case_sensitive, self.block_match_whole_word)
            if block_pattern:
                try:
                    if re.search(block_pattern, modified_text, block_flags):
                        action_taken = True
                        original_before_block = modified_text # For logging
                        if self.block_response_message:
                            modified_text = self.block_response_message
                            logger.info(f"[{self.plugin_id}] Blocked: Text replaced. Original: '{original_before_block}' -> New: '{modified_text}'")
                        else:
                            modified_text = ""
                            logger.info(f"[{self.plugin_id}] Blocked: Text cleared. Original: '{original_before_block}'")
                        response.completion_text = modified_text
                        return # Exit after blocking
                except re.error as e: 
                    logger.error(f"[{self.plugin_id}] Block regex error for pattern '{block_pattern}': {e}")

        # Delete filter
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
                    logger.error(f"[{self.plugin_id}] Delete regex error for pattern '{delete_pattern}': {e}")
        
        if action_taken:
            response.completion_text = modified_text
            # No need for a final log here if individual actions are logged
        # else: logger.info(f"[{self.plugin_id}] No changes made by filters to: '{original_text}'") # Removed for less verbosity