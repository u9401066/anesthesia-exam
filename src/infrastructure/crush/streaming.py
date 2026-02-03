"""Crush Streaming Client - 流式輸出支援"""

from __future__ import annotations

import subprocess
import asyncio
from pathlib import Path
from typing import AsyncIterator, Optional, Iterator, List
from dataclasses import dataclass
import threading
import queue


@dataclass
class CrushStreamConfig:
    """Crush 流式配置"""
    executable_path: str = r"D:\workspace260203\crush\crush.exe"
    working_dir: Optional[str] = None
    model: Optional[str] = None


class CrushStreamingClient:
    """Crush CLI 流式客戶端 - 支援逐字輸出"""
    
    def __init__(self, config: Optional[CrushStreamConfig] = None):
        self.config = config or CrushStreamConfig()
        self._validate_executable()
    
    def _validate_executable(self) -> None:
        """驗證 Crush 執行檔存在"""
        if not Path(self.config.executable_path).exists():
            raise FileNotFoundError(
                f"Crush executable not found: {self.config.executable_path}"
            )
    
    def _build_command(self, prompt: str) -> List[str]:
        """建構命令列參數"""
        cmd: List[str] = [self.config.executable_path, "run", "--verbose"]
        
        if self.config.model:
            cmd.extend(["--model", self.config.model])
        
        if self.config.working_dir:
            cmd.extend(["--cwd", self.config.working_dir])
        
        cmd.append(prompt)
        return cmd
    
    def stream(self, prompt: str) -> Iterator[str]:
        """
        同步流式執行 prompt
        
        Args:
            prompt: 要發送的提示
            
        Yields:
            逐塊輸出的文字
        """
        cmd = self._build_command(prompt)
        
        process: subprocess.Popen[str] = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
            cwd=self.config.working_dir,
        )
        
        try:
            assert process.stdout is not None
            assert process.stderr is not None
            
            # 逐行讀取輸出
            for line in iter(process.stdout.readline, ''):
                if line:
                    yield line
            
            process.wait()
            
            if process.returncode != 0:
                stderr = process.stderr.read()
                raise RuntimeError(f"Crush error: {stderr}")
                
        finally:
            process.terminate()
    
    def stream_chars(self, prompt: str, chunk_size: int = 1) -> Iterator[str]:
        """
        逐字元流式輸出
        
        Args:
            prompt: 要發送的提示
            chunk_size: 每次輸出的字元數
            
        Yields:
            逐字元輸出
        """
        cmd = self._build_command(prompt)
        
        process: subprocess.Popen[str] = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0,  # Unbuffered
            cwd=self.config.working_dir,
        )
        
        try:
            assert process.stdout is not None
            assert process.stderr is not None
            
            while True:
                char = process.stdout.read(chunk_size)
                if not char:
                    break
                yield char
            
            process.wait()
            
            if process.returncode != 0:
                stderr = process.stderr.read()
                raise RuntimeError(f"Crush error: {stderr}")
                
        finally:
            process.terminate()
    
    async def astream(self, prompt: str) -> AsyncIterator[str]:
        """
        異步流式執行 prompt
        
        Args:
            prompt: 要發送的提示
            
        Yields:
            逐塊輸出的文字
        """
        cmd = self._build_command(prompt)
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.config.working_dir,
        )
        
        try:
            assert process.stdout is not None
            assert process.stderr is not None
            
            async for line in process.stdout:
                yield line.decode('utf-8')
            
            await process.wait()
            
            if process.returncode != 0:
                stderr = await process.stderr.read()
                raise RuntimeError(f"Crush error: {stderr.decode('utf-8')}")
                
        finally:
            process.terminate()


class ThreadedCrushStream:
    """
    線程化的 Crush 流式客戶端
    適用於 Streamlit 等需要在主線程顯示的場景
    """
    
    def __init__(self, config: Optional[CrushStreamConfig] = None):
        self.config = config or CrushStreamConfig()
        self.output_queue: queue.Queue[Optional[str]] = queue.Queue()
        self._process: Optional[subprocess.Popen[str]] = None
        self._thread: Optional[threading.Thread] = None
        self._is_running = False
    
    def start(self, prompt: str) -> None:
        """開始執行並在背景收集輸出"""
        cmd: List[str] = [self.config.executable_path, "run", "--verbose"]
        
        if self.config.model:
            cmd.extend(["--model", self.config.model])
        
        if self.config.working_dir:
            cmd.extend(["--cwd", self.config.working_dir])
        
        cmd.append(prompt)
        
        self._is_running = True
        self._thread = threading.Thread(
            target=self._run_process,
            args=(cmd,),
            daemon=True
        )
        self._thread.start()
    
    def _run_process(self, cmd: List[str]) -> None:
        """在背景線程執行進程"""
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=self.config.working_dir,
            )
            
            assert self._process.stdout is not None
            
            for line in iter(self._process.stdout.readline, ''):
                if not self._is_running:
                    break
                if line:
                    self.output_queue.put(line)
            
            self._process.wait()
            
        except Exception as e:
            self.output_queue.put(f"[ERROR] {e}")
        finally:
            self._is_running = False
            self.output_queue.put(None)  # 結束信號
    
    def get_output(self, timeout: float = 0.1) -> Optional[str]:
        """取得下一塊輸出（非阻塞）"""
        try:
            return self.output_queue.get(timeout=timeout)
        except queue.Empty:
            return ""
    
    def is_running(self) -> bool:
        """檢查是否還在執行"""
        return self._is_running
    
    def stop(self) -> None:
        """停止執行"""
        self._is_running = False
        if self._process:
            self._process.terminate()
