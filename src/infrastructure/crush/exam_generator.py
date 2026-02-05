"""
Exam Generator - Crush 整合的考題生成器

提供細粒度的題目生成控制：
- 真正的流式輸出
- 完整的 logging
- MCP 工具調用追蹤
- 題目/選項/詳解分段處理
"""

import subprocess
import json
import re
import logging
import time
from pathlib import Path
from typing import Generator, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# 設定 logger
logger = logging.getLogger(__name__)


class GenerationPhase(Enum):
    """生成階段"""
    INITIALIZING = "initializing"
    THINKING = "thinking"
    GENERATING_QUESTION = "generating_question"
    GENERATING_OPTIONS = "generating_options"
    GENERATING_EXPLANATION = "generating_explanation"
    CALLING_MCP = "calling_mcp"
    SAVED = "saved"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class GenerationEvent:
    """生成事件"""
    phase: GenerationPhase
    content: str
    question_index: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


@dataclass
class QuestionDraft:
    """題目草稿（生成中的題目）"""
    index: int
    question_text: str = ""
    options: list = field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    difficulty: str = "medium"
    topics: list = field(default_factory=list)
    question_id: Optional[str] = None
    is_saved: bool = False
    
    def to_dict(self) -> dict:
        return {
            "id": self.question_id,
            "question_text": self.question_text,
            "options": self.options,
            "correct_answer": self.correct_answer,
            "explanation": self.explanation,
            "difficulty": self.difficulty,
            "topics": self.topics,
        }
    
    def is_complete(self) -> bool:
        """檢查題目是否完整"""
        return bool(
            self.question_text and 
            len(self.options) >= 2 and 
            self.correct_answer
        )


class ExamGenerator:
    """
    考題生成器
    
    使用 Crush CLI 調用 AI + MCP 生成考題，
    提供流式輸出和細粒度控制。
    """
    
    def __init__(
        self,
        crush_path: str = r"D:\workspace260203\crush\crush.exe",
        working_dir: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.crush_path = Path(crush_path)
        self.working_dir = Path(working_dir) if working_dir else Path.cwd()
        self.model = model
        
        # 生成狀態
        self.current_phase = GenerationPhase.INITIALIZING
        self.questions: list[QuestionDraft] = []
        self.current_question: Optional[QuestionDraft] = None
        self.raw_output = ""
        
        # 回呼函數
        self._on_event: Optional[Callable[[GenerationEvent], None]] = None
        self._on_chunk: Optional[Callable[[str], None]] = None
        
        self._validate()
    
    def _validate(self):
        """驗證 Crush 執行檔"""
        if not self.crush_path.exists():
            raise FileNotFoundError(f"Crush not found: {self.crush_path}")
    
    def set_event_handler(self, handler: Callable[[GenerationEvent], None]):
        """設定事件處理器"""
        self._on_event = handler
    
    def set_chunk_handler(self, handler: Callable[[str], None]):
        """設定文字塊處理器（每次收到新文字時觸發）"""
        self._on_chunk = handler
    
    def _emit_event(self, phase: GenerationPhase, content: str, **kwargs):
        """發送事件"""
        self.current_phase = phase
        event = GenerationEvent(
            phase=phase,
            content=content,
            question_index=len(self.questions),
            metadata=kwargs,
        )
        logger.info(f"[{phase.value}] {content[:100]}...")
        
        if self._on_event:
            self._on_event(event)
    
    def _emit_chunk(self, chunk: str):
        """發送文字塊"""
        if self._on_chunk:
            self._on_chunk(chunk)
    
    def _parse_mcp_result(self, text: str) -> Optional[dict]:
        """解析 MCP 工具調用結果"""
        # 尋找 JSON 格式的結果
        patterns = [
            r'\{[^{}]*"question_id"\s*:\s*"[^"]+?"[^{}]*\}',
            r'\{[^{}]*"success"\s*:\s*true[^{}]*\}',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
            for match in matches:
                try:
                    result = json.loads(match)
                    if result.get("question_id"):
                        return result
                except json.JSONDecodeError:
                    continue
        
        # 嘗試尋找題目 ID 格式
        id_match = re.search(r'題目\s*ID[：:]\s*[`"]?([a-f0-9-]{36})[`"]?', text)
        if id_match:
            return {"question_id": id_match.group(1), "success": True}
        
        return None
    
    def _parse_question_content(self, text: str) -> Optional[QuestionDraft]:
        """從文字中解析題目內容"""
        draft = QuestionDraft(index=len(self.questions) + 1)
        
        # 解析題目文字
        q_patterns = [
            r'\*\*題目[：:]\*\*\s*(.+?)(?=\*\*選項|\*\*Options|[A-D][.、]|$)',
            r'題目[：:]\s*(.+?)(?=選項|[A-D][.、]|$)',
            r'(?:^|\n)(\d+[.、]\s*.+?)(?=\n[A-D][.、]|$)',
        ]
        
        for pattern in q_patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                draft.question_text = match.group(1).strip()
                break
        
        # 解析選項
        opt_pattern = r'([A-D])[.、:：]\s*(.+?)(?=[A-D][.、:：]|\*\*答案|\*\*正確|答案[：:]|$)'
        for match in re.finditer(opt_pattern, text, re.DOTALL):
            opt_text = match.group(2).strip()
            if opt_text and len(opt_text) > 1:
                draft.options.append(opt_text)
        
        # 解析答案
        ans_patterns = [
            r'\*\*(?:答案|正確答案)[：:]\*\*\s*([A-D])',
            r'(?:答案|正確答案)[：:]\s*([A-D])',
            r'正確選項[是為：:]\s*([A-D])',
        ]
        
        for pattern in ans_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                draft.correct_answer = match.group(1).upper()
                break
        
        # 解析詳解
        exp_patterns = [
            r'\*\*(?:解析|詳解|說明)[：:]\*\*\s*(.+?)(?=\*\*|題目 ID|$)',
            r'(?:解析|詳解|說明)[：:]\s*(.+?)(?=題目|$)',
        ]
        
        for pattern in exp_patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                draft.explanation = match.group(1).strip()
                break
        
        # 解析難度
        diff_match = re.search(r'難度[：:]\s*(easy|medium|hard|簡單|中等|困難)', text, re.IGNORECASE)
        if diff_match:
            diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
            draft.difficulty = diff_map.get(diff_match.group(1), diff_match.group(1).lower())
        
        if draft.question_text or draft.options:
            return draft
        
        return None
    
    def generate(
        self,
        num_questions: int = 5,
        question_type: str = "單選題",
        difficulty: str = "medium",
        topics: list[str] = None,
        source_doc: str = None,
        additional_instructions: str = None,
    ) -> Generator[GenerationEvent, None, list[QuestionDraft]]:
        """
        流式生成考題
        
        Yields:
            GenerationEvent: 生成事件
            
        Returns:
            list[QuestionDraft]: 生成的題目列表
        """
        self.questions = []
        self.raw_output = ""
        
        # 建構 prompt
        prompt = self._build_prompt(
            num_questions, question_type, difficulty,
            topics, source_doc, additional_instructions
        )
        
        logger.info(f"Starting generation: {num_questions} questions, type={question_type}, difficulty={difficulty}")
        self._emit_event(GenerationPhase.INITIALIZING, "正在初始化生成器...")
        
        # 建構命令
        cmd = [
            str(self.crush_path),
            "run",
            "--cwd", str(self.working_dir),
            prompt
        ]
        
        if self.model:
            cmd.insert(2, "--model")
            cmd.insert(3, self.model)
        
        logger.debug(f"Command: {' '.join(cmd[:4])}...")
        
        # 執行 Crush
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 合併 stderr 到 stdout
            text=True,
            bufsize=1,  # 行緩衝
            encoding='utf-8',
            errors='replace',
        )
        
        try:
            current_question_buffer = ""
            last_saved_count = 0
            
            self._emit_event(GenerationPhase.THINKING, "AI 正在思考...")
            
            for line in iter(process.stdout.readline, ''):
                if not line:
                    continue
                
                # 發送原始文字塊
                self._emit_chunk(line)
                self.raw_output += line
                current_question_buffer += line
                
                # 偵測 MCP 調用
                mcp_result = self._parse_mcp_result(current_question_buffer)
                if mcp_result and mcp_result.get("question_id"):
                    # 解析題目內容
                    draft = self._parse_question_content(current_question_buffer)
                    if draft:
                        draft.question_id = mcp_result["question_id"]
                        draft.is_saved = True
                        self.questions.append(draft)
                        
                        self._emit_event(
                            GenerationPhase.SAVED,
                            f"題目 {len(self.questions)} 已儲存",
                            question=draft.to_dict(),
                            question_id=draft.question_id,
                        )
                        
                        logger.info(f"Question {len(self.questions)} saved: {draft.question_id}")
                    
                    # 重置緩衝區
                    current_question_buffer = ""
                
                # 偵測生成階段
                if "題目" in line or "Question" in line:
                    self._emit_event(GenerationPhase.GENERATING_QUESTION, line.strip())
                elif re.match(r'^[A-D][.、]', line.strip()):
                    self._emit_event(GenerationPhase.GENERATING_OPTIONS, line.strip())
                elif "解析" in line or "詳解" in line:
                    self._emit_event(GenerationPhase.GENERATING_EXPLANATION, line.strip())
                elif "exam_save_question" in line.lower():
                    self._emit_event(GenerationPhase.CALLING_MCP, "正在儲存題目...")
                
                yield GenerationEvent(
                    phase=self.current_phase,
                    content=line,
                    question_index=len(self.questions),
                )
            
            process.wait()
            
            if process.returncode != 0:
                self._emit_event(GenerationPhase.ERROR, f"生成失敗 (code: {process.returncode})")
            else:
                self._emit_event(
                    GenerationPhase.COMPLETED,
                    f"生成完成，共 {len(self.questions)} 題",
                    total=len(self.questions),
                )
            
        except Exception as e:
            logger.error(f"Generation error: {e}")
            self._emit_event(GenerationPhase.ERROR, str(e))
            raise
        finally:
            process.terminate()
        
        return self.questions
    
    def _build_prompt(
        self,
        num_questions: int,
        question_type: str,
        difficulty: str,
        topics: list[str],
        source_doc: str,
        additional_instructions: str,
    ) -> str:
        """建構生成 prompt"""
        
        diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
        diff_en = diff_map.get(difficulty, difficulty)
        
        prompt = f"""請生成 {num_questions} 道{question_type}。

## 考題配置
- 題型: {question_type}
- 難度: {difficulty} ({diff_en})
- 題數: {num_questions}
"""
        
        if topics:
            prompt += f"- 知識點範圍: {', '.join(topics)}\n"
        if source_doc:
            prompt += f"- 參考教材: {source_doc}\n"
        if additional_instructions:
            prompt += f"- 額外要求: {additional_instructions}\n"
        
        prompt += """
## 重要指示
1. 每生成一題，**立即**使用 `exam_save_question` MCP 工具儲存
2. 儲存後繼續生成下一題
3. 每題必須包含完整資訊

## 每題格式
**題目:** [題目文字]
**選項:**
A. [選項A]
B. [選項B]
C. [選項C]
D. [選項D]
**答案:** [A/B/C/D]
**難度:** [easy/medium/hard]
**解析:** [詳細解說]

## MCP 工具參數
exam_save_question 需要：
- question_text: 題目文字
- options: ["選項A", "選項B", "選項C", "選項D"]
- correct_answer: "A" (或 B/C/D)
- explanation: 詳解
- difficulty: "easy"/"medium"/"hard"
- topics: ["知識點1", "知識點2"]

請開始生成第 1 題。"""
        
        return prompt


# 便利函數
def create_generator(working_dir: str = None) -> ExamGenerator:
    """建立考題生成器"""
    return ExamGenerator(working_dir=working_dir)
