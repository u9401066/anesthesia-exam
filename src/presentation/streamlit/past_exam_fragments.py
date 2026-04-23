"""Render helpers for image-based past-exam questions."""

from __future__ import annotations

from pathlib import Path

import streamlit as st


def render_past_exam_question_assets(question: dict) -> None:
    """Render figure assets / source page preview for a past-exam question when available."""
    option_assets = list(question.get("option_figure_assets", []) or [])
    figure_assets = list(question.get("figure_assets", []) or [])
    source_page_image_path = str(question.get("source_page_image_path") or "").strip()
    image_asset_note = str(question.get("image_asset_note") or "").strip()
    image_asset_status = str(question.get("image_asset_status") or "").strip()

    if option_assets:
        st.caption("圖像選項")
        columns = st.columns(2)
        for index, asset in enumerate(option_assets):
            column = columns[index % 2]
            with column:
                st.caption(f"{asset.get('label', chr(65 + index))}. {asset.get('id', '')}")
                st.image(asset["path"])

    if figure_assets:
        with st.expander("🖼️ 題目相關圖像", expanded=not option_assets):
            for index, asset in enumerate(figure_assets, start=1):
                caption = str(asset.get("caption") or "").strip() or f"同頁圖像 {index}"
                st.image(asset["path"], caption=caption)

    if source_page_image_path:
        preview_path = Path(source_page_image_path)
        if preview_path.exists():
            with st.expander("📄 原題頁面預覽", expanded=False):
                st.image(str(preview_path), caption=f"來源頁面 p.{question.get('source_page', '-')} 的原頁預覽")

    if image_asset_status == "needs_reingest" and image_asset_note:
        st.warning(image_asset_note)