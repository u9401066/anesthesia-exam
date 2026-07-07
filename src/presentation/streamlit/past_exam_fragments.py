"""Render helpers for image-based past-exam questions."""

from __future__ import annotations

from pathlib import Path

import streamlit as st


def _option_label(index: int) -> str:
    if 0 <= index < 26:
        return chr(65 + index)
    return str(index + 1)


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
                label = str(asset.get("label") or _option_label(index))
                option_id = str(asset.get("id") or "").strip() or f"option_{index}"
                path = str(asset.get("path") or "").strip()
                st.caption(f"{label}. {option_id}")
                if path and Path(path).exists():
                    st.image(
                        path,
                        caption=f"{label}（{option_id}）",
                        key=f"past_exam_option_asset_{question.get('id', '')}_{option_id}_{index}",
                    )
                else:
                    st.warning(f"找不到選項圖像: {path or '未提供路徑'}")

    if figure_assets:
        with st.expander("🖼️ 題目相關圖像", expanded=not option_assets):
            for index, asset in enumerate(figure_assets, start=1):
                caption = str(asset.get("caption") or "").strip() or f"同頁圖像 {index}"
                path = str(asset.get("path") or "").strip()
                if path and Path(path).exists():
                    st.image(
                        path,
                        caption=caption,
                        key=f"past_exam_figure_asset_{question.get('id', '')}_{index}",
                    )
                else:
                    st.warning(f"找不到題目圖像: {path or '未提供路徑'}")

    if source_page_image_path:
        preview_path = Path(source_page_image_path)
        if preview_path.exists():
            with st.expander("📄 原題頁面預覽", expanded=False):
                st.image(
                    str(preview_path),
                    caption=f"來源頁面 p.{question.get('source_page', '-')}",
                    key=f"past_exam_source_page_{question.get('id', '')}",
                )

    if image_asset_status == "needs_reingest" and image_asset_note:
        st.warning(image_asset_note)
