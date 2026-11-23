import importlib.util
import os
import subprocess
import sys
from pathlib import Path


# ============================================================
# SETTINGS
# ============================================================

# Output image format: "webp", "jpg" or "png"
OUTPUT_FORMAT = "webp"

# Render resolution
DPI = 200

# WebP / JPG quality (1-100)
IMAGE_QUALITY = 90

# PNG compression level (0-9)
PNG_COMPRESSION = 6

# Replace images that already exist
OVERWRITE = True

# Proxy used when pip installs missing libraries
USE_PROXY = True

HTTP_PROXY = "http://192.168.43.1:10809"
HTTPS_PROXY = "http://192.168.43.1:10809"


# ============================================================
# PATHS
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_DIR = SCRIPT_DIR / "Input"
OUTPUT_DIR = SCRIPT_DIR / "Output"


# ============================================================
# DEPENDENCIES
# ============================================================

def configure_proxy():
    """Set proxy environment variables for this process and child processes."""
    if not USE_PROXY:
        return

    os.environ["HTTP_PROXY"] = HTTP_PROXY
    os.environ["HTTPS_PROXY"] = HTTPS_PROXY
    os.environ["http_proxy"] = HTTP_PROXY
    os.environ["https_proxy"] = HTTPS_PROXY


def check_dependencies():
    """Check and install the libraries required by the converter."""
    dependencies = {
        "fitz": "PyMuPDF",
        "PIL": "Pillow",
    }

    configure_proxy()

    for module_name, package_name in dependencies.items():
        if importlib.util.find_spec(module_name) is not None:
            print(f"[OK] {package_name} is already installed.")
            continue

        print(f"\n[INSTALL] Installing {package_name}...")

        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
        ]

        if USE_PROXY:
            command.extend(["--proxy", HTTPS_PROXY])

        command.append(package_name)

        try:
            result = subprocess.run(command, check=False)
        except Exception as error:
            raise RuntimeError(
                f"Could not start pip while installing {package_name}: {error}"
            ) from error

        if result.returncode != 0:
            raise RuntimeError(
                f"pip could not install {package_name}.\n"
                f"Check that the proxy is running and reachable:\n"
                f"{HTTPS_PROXY}"
            )

        # Verify that the module became importable after installation.
        importlib.invalidate_caches()
        if importlib.util.find_spec(module_name) is None:
            raise RuntimeError(
                f"{package_name} installation finished, but "
                f"Python still cannot find module '{module_name}'."
            )

        print(f"[OK] {package_name} installed successfully.")


# ============================================================
# FOLDERS
# ============================================================

def create_directories():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# PDF CONVERSION
# ============================================================

def process_pdf(pdf_path):
    import fitz
    from PIL import Image

    output_folder = OUTPUT_DIR / pdf_path.stem
    output_folder.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 64)
    print(f"PDF: {pdf_path.name}")
    print(f"Output: {output_folder}")

    successful_pages = 0
    skipped_pages = 0
    failed_pages = 0

    # PDF points are based on 72 DPI.
    scale = DPI / 72.0
    render_matrix = fitz.Matrix(scale, scale)

    try:
        document = fitz.open(str(pdf_path))
    except Exception as error:
        raise RuntimeError(f"Cannot open PDF: {error}") from error

    with document:
        if document.needs_pass:
            raise RuntimeError(
                "This PDF is password-protected. "
                "The script currently does not ask for a password."
            )

        total_pages = document.page_count
        print(f"Pages: {total_pages}")

        if total_pages == 0:
            print("The PDF contains no pages.")
            return 0, 0, 0

        for page_index in range(total_pages):
            page_number = page_index + 1
            extension = "jpg" if OUTPUT_FORMAT == "jpg" else OUTPUT_FORMAT
            output_file = output_folder / f"page_{page_number:04d}.{extension}"

            if output_file.exists() and not OVERWRITE:
                print(f"[{page_number}/{total_pages}] Skipped: already exists")
                skipped_pages += 1
                continue

            try:
                page = document.load_page(page_index)

                # Render only this page; the whole PDF is never loaded as images.
                pixmap = page.get_pixmap(
                    matrix=render_matrix,
                    colorspace=fitz.csRGB,
                    alpha=False,
                    annots=True,
                )

                # Build a Pillow image directly from RGB pixel data.
                image = Image.frombytes(
                    "RGB",
                    (pixmap.width, pixmap.height),
                    pixmap.samples,
                )

                try:
                    if OUTPUT_FORMAT == "webp":
                        image.save(
                            output_file,
                            format="WEBP",
                            quality=IMAGE_QUALITY,
                            method=4,
                        )

                    elif OUTPUT_FORMAT == "jpg":
                        image.save(
                            output_file,
                            format="JPEG",
                            quality=IMAGE_QUALITY,
                            optimize=True,
                        )

                    elif OUTPUT_FORMAT == "png":
                        image.save(
                            output_file,
                            format="PNG",
                            compress_level=PNG_COMPRESSION,
                        )
                finally:
                    image.close()

                successful_pages += 1
                print(f"[{page_number}/{total_pages}] OK: {output_file.name}")

            except Exception as error:
                failed_pages += 1
                print(f"[{page_number}/{total_pages}] ERROR: {error}")

    print("-" * 64)
    print(f"Successful: {successful_pages}")
    print(f"Skipped:    {skipped_pages}")
    print(f"Failed:     {failed_pages}")

    return successful_pages, skipped_pages, failed_pages


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 64)
    print("                  PDF BATCH CONVERTER")
    print("=" * 64)

    if OUTPUT_FORMAT not in ("webp", "jpg", "png"):
        raise ValueError(
            "OUTPUT_FORMAT must be 'webp', 'jpg' or 'png'."
        )

    if DPI <= 0:
        raise ValueError("DPI must be greater than zero.")

    if not 1 <= IMAGE_QUALITY <= 100:
        raise ValueError("IMAGE_QUALITY must be between 1 and 100.")

    if not 0 <= PNG_COMPRESSION <= 9:
        raise ValueError("PNG_COMPRESSION must be between 0 and 9.")

    create_directories()

    print("\nChecking dependencies...")
    if USE_PROXY:
        print(f"Proxy enabled: {HTTPS_PROXY}")
    else:
        print("Proxy disabled.")

    check_dependencies()

    pdf_files = sorted(
        (
            path for path in INPUT_DIR.iterdir()
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda path: path.name.lower(),
    )

    if not pdf_files:
        print("\nNo PDF files found in Input.")
        print(f"Put PDF files here: {INPUT_DIR}")
        return

    print(f"\nPDF files found: {len(pdf_files)}")
    print(f"Format: {OUTPUT_FORMAT.upper()}")
    print(f"DPI: {DPI}")
    print(f"Quality: {IMAGE_QUALITY}")
    print(f"Overwrite: {OVERWRITE}")

    total_successful = 0
    total_skipped = 0
    total_failed = 0
    successful_files = 0
    failed_files = 0

    for file_index, pdf_path in enumerate(pdf_files, start=1):
        print(f"\nFILE {file_index}/{len(pdf_files)}")

        try:
            successful, skipped, failed = process_pdf(pdf_path)

            total_successful += successful
            total_skipped += skipped
            total_failed += failed

            if failed == 0:
                successful_files += 1
            else:
                failed_files += 1

        except Exception as error:
            failed_files += 1
            print(f"\nERROR processing {pdf_path.name}:")
            print(error)

    print("\n" + "=" * 64)
    print("                    FINISHED")
    print("=" * 64)
    print(f"PDF files:          {len(pdf_files)}")
    print(f"Files without errors: {successful_files}")
    print(f"Files with errors:    {failed_files}")
    print(f"Pages converted:    {total_successful}")
    print(f"Pages skipped:      {total_skipped}")
    print(f"Pages failed:       {total_failed}")
    print(f"\nOutput folder: {OUTPUT_DIR}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nFATAL ERROR:\n{error}")
    finally:
        try:
            input("\nPress Enter to exit...")
        except EOFError:
            pass
