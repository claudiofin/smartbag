#!/bin/bash
# Fetch the datasheets hardware/bom.py quotes, into hardware/datasheets/.
#
# ⚠️ THE PDFS ARE NOT COMMITTED, ON PURPOSE. They are third-party copyrighted
# documents and this is a public repository; downloading one to check a package
# dimension is ordinary use, republishing a vendor's datasheet from someone
# else's GitHub is not. So the repo carries the URLs and the numbers read out of
# them, and this script puts the documents back on your disk.
#
# ⛔ Several vendors block scripted downloads (Mouser, LCSC, Hirose return an
# HTML challenge page with a .pdf name). Those are marked FAIL and left to the
# browser; hardware/bom.py has the link. A file that is not a PDF is deleted
# rather than kept, so nothing here can leave an HTML error page sitting where a
# datasheet is expected.
set -e
cd "$(dirname "$0")/.."
mkdir -p hardware/datasheets
cd hardware/datasheets
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"

get() {
  if [ -s "$1" ]; then echo "  have $1"; return; fi
  curl -sL --max-time 90 -A "$UA" -o "_t.pdf" "$2" 2>/dev/null || true
  if file _t.pdf 2>/dev/null | grep -q PDF; then
    mv _t.pdf "$1"; echo "  OK   $1 ($(du -h "$1" | cut -f1))"
  else
    rm -f _t.pdf; echo "  FAIL $1 — fetch it by hand: $2"
  fi
}

get A121_acconeer.pdf   "https://developer.acconeer.com/download/a121-datasheet"
get nPM1300_nordic.pdf  "https://download.mikroe.com/documents/datasheets/nPM1300_datasheet.pdf"
get BMI270_bosch.pdf    "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi270-ds000.pdf"
get DRV5032_ti.pdf      "https://www.ti.com/lit/ds/symlink/drv5032.pdf"
# ⭐ 13 MB, and worth every byte: it is the only source found that carries the
# QFN48 pin assignment figure. Nordic's own docs site paywalls the PDF and
# renders the table across page breaks in a way no text extractor survives — the
# figure had to be rasterised and read as an image.
get nRF54L15_nordic.pdf "https://files.seeedstudio.com/wiki/XIAO_nRF54L15/Getting_Start/Nordic_nRF54L15_Datasheet_v1.0.pdf"
