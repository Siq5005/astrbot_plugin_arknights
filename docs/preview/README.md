# 预览与设计稿

| 文件 | 说明 |
|---|---|
| `help.jpg` 等 13 张 | **插件实际渲染输出**（原生 1800px，未做缩放，与机器人发送的图片字节一致），由 `tests/render_preview.py` 用固定测试数据生成 |
| `ui-design.png` | 用 gpt-image-2.5 生成的 UI 设计稿，卡片版式按此实现 |
| `ui-prompt.md` | 生成设计稿与插件图标的提示词、调用方式与裁切经验 |

## 重新生成预览图

```bash
python tests/render_preview.py
```

会用固定测试数据渲染全部卡片，并把渲染器输出原样复制到 `docs/preview/`（不缩放）。
