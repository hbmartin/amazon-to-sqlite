import re

import requests
from bs4 import BeautifulSoup


def check_book_formats(asin: str) -> None:
    url = f"https://www.amazon.com/dp/{asin}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        # Extract book title
        title_element = soup.select_one("#title") or soup.select_one("#productTitle")
        title = title_element.text.strip() if title_element else "Title not found"
        print(f"Book Title: {title}")

        # Check for formats
        formats = {
            "Hardcover": False,
            "Paperback": False,
            "Kindle": False,
            "Audiobook": False,
        }

        # Check main format
        format_element = soup.select_one("#productSubtitle")
        if format_element:
            format_text = format_element.text.strip()
            for fmt in formats:
                if fmt.lower() in format_text.lower():
                    formats[fmt] = True

        # Check for Kindle format
        kindle_element = soup.find(
            "a",
            {"href": re.compile(r"/dp/\w+/ref=dp_ob_title_def")},
        ) or soup.find("a", {"href": re.compile(r"/dp/\w+/ref=tmm_kin_swatch_0")})
        if kindle_element and "kindle" in kindle_element.text.lower():
            formats["Kindle"] = True

        # Check for Audiobook format
        audiobook_element = soup.find(
            "a",
            {"href": re.compile(r"/dp/\w+/ref=tmm_aud_swatch_0")},
        )
        if audiobook_element and "audiobook" in audiobook_element.text.lower():
            formats["Audiobook"] = True

        print("Available formats:")
        for fmt, available in formats.items():
            print(f"{fmt}: {'Yes' if available else 'No'}")

    except requests.RequestException as e:
        print(f"An error occurred while fetching the page: {e!s}")
    except Exception as e:  # noqa: BLE001
        print(f"An error occurred: {e!s}")


# Example usage
asin = "1098168100"  # Replace with your book's ASIN
check_book_formats(asin)
