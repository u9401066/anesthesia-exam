"""Crush Client - 基本同步調用"""

import subprocess
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class CrushConfig:
    """Crush 配置"""
    executable_path: str = r"D:\workspace260203\crush\crush.exe"
    working_dir: Optional[str] = None
    model: Optional[str] = None
    timeout: int = 120


class CrushClient:
    """Crush CLI 同步客戶端"""
    
    def __init__(self, config: Optional[CrushConfig] = None):
        self.config = config or CrushConfig()
        self._validate_executable()
    
    def _validate_executable(self) -> None:
        """驗證 Crush 執行檔存在"""
        if not Path(self.config.executable_path).exists():
            raise FileNotFoundError(
                f"Crush executable not found: {self.config.executable_path}"
            )
    
    def run(self, prompt: str, quiet: bool = True) -> str:
        """
        執行單次 prompt 並返回結果
        
        Args:
            prompt: 要發送的提示
            quiet: 是否隱藏 spinner
            
        Returns:
            模型回應文字
        """
        cmd = [self.config.executable_path, "run"]
        
        if quiet:
            cmd.append("--quiet")
        
        if self.config.model:
            cmd.extend(["--model", self.config.model])
        
        if self.config.working_dir:
            cmd.extend(["--cwd", self.config.working_dir])
        
        cmd.append(prompt)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                cwd=self.config.working_dir,
                encoding='utf-8',
                errors='replace',
            )
            
            if result.returncode != 0:
                raise RuntimeError(
                    f"Crush error (code {result.returncode}): {result.stderr}"
                )
            
            return result.stdout.strip()
            
        except subprocess.TimeoutExpired:
            raise TimeoutError(
                f"Crush command timed out after {self.config.timeout} seconds"
            )
    
    def check_connection(self) -> bool:
        """檢查 Crush 是否可用"""
        try:
            result = self.run("回答數字 42", quiet=True)
            return "42" in result
        except Exception:
            return False
