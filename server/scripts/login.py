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


def render_qr(text: str) -> None:
    """Print a QR code for the given payload to the terminal.

    Args:
        text: Payload to encode, here the ``hypergryph://`` login URL.
    """
    try:
        import qrcode
    except ImportError:
        print("未安装 qrcode，无法在终端渲染二维码。")
        print("请在能生成二维码的工具里手工编码下面的内容：")
        print(text)
        return
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
    args = parser.parse_args()

    client = HypergryphClient()
    try:
        qr = await client.create_qr()
        print("请使用「森空岛」APP 扫描下面的二维码：\n")
        render_qr(qr["scan_url"])
        print(f"\nscan_id={qr['scan_id']}\n等待扫码…")

        waited = 0
        while waited < POLL_TIMEOUT_SECONDS:
            scan_code = await client.poll_qr(qr["scan_id"])
            if scan_code:
                token = await client.get_token_by_scan_code(scan_code)
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
