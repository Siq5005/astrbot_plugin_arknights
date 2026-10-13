"""One-time Skland QR login for the aggregator.

Run it on the host that serves the aggregator, scan the printed QR with the
森空岛 app, and the long-lived passport token is written to the credential file.
The token only needs replacing if the account logs out or the token is revoked.

Usage:
    python scripts/login.py [--output /opt/arksource/credentials.json]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.credentials import save_user_token  # noqa: E402
from app.hypergryph_client import HypergryphClient  # noqa: E402

POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 180


def render_qr(text: str, image_path: Path) -> None:
    """Render a QR code for the given payload, to a file and to the terminal.

    The terminal rendering uses block characters and therefore needs a strictly
    monospaced font; a chat window or a proportional terminal font shears it
    into something unscannable, so the file is the artifact that matters.

    The SVG factory is deliberate: it is the only ``qrcode`` image backend that
    needs nothing outside the standard library. ``qrcode.make()`` pulls in
    Pillow and ``PyPNGImage`` pulls in PyPNG, either of which would add a
    dependency the service does not otherwise carry.

    Args:
        text: Payload to encode, here the ``hypergryph://`` login URL.
        image_path: Where to write the image. Mode 0600, since the payload is a
            login URL — short lived, but still a credential.
    """
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        print("未安装 qrcode，无法渲染二维码。")
        print("请在能生成二维码的工具里手工编码下面的内容：")
        print(text)
        return

    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(image_path)
    os.chmod(image_path, 0o600)
    print(f"二维码已写入 {image_path}（打开图片再扫，比看终端可靠）")
    print(f"图片也扫不出的话，把这串交给任意二维码生成器：\n{text}")

    qr = qrcode.QRCode(border=1)
    qr.add_data(text)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


async def main() -> int:
    """Run the QR login flow.

    Returns:
        Process exit code: 0 on success, 1 on timeout or failure.
    """
    parser = argparse.ArgumentParser(description="Skland QR login for arksource")
    parser.add_argument(
        "--output",
        default=os.environ.get(
            "ARKSOURCE_CREDENTIAL_FILE", "/opt/arksource/credentials.json"
        ),
        help="credential file to write",
    )
    parser.add_argument(
        "--qr-image",
        default="/opt/arksource/login-qr.svg",
        help="where to write the scannable QR image",
    )
    args = parser.parse_args()

    client = HypergryphClient()
    try:
        qr = await client.create_qr()
        print("请使用「森空岛」APP 扫描下面的二维码：\n")
        render_qr(qr["scan_url"], Path(args.qr_image))
        print(f"\nscan_id={qr['scan_id']}\n等待扫码…")

        waited = 0
        while waited < POLL_TIMEOUT_SECONDS:
            scan_code = await client.poll_qr(qr["scan_id"])
            if scan_code:
                token = await client.get_token_by_scan_code(scan_code)
                if not token:
                    print("登录失败：未获取到凭证，请重新运行本脚本。")
                    return 1
                save_user_token(Path(args.output), token)
                print(f"登录成功，凭证已写入 {args.output}")
                return 0
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            waited += POLL_INTERVAL_SECONDS

        print("等待扫码超时，请重新运行本脚本。")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
