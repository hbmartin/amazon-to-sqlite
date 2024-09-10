import bottlenose
import xmltodict

# Replace these with your own credentials
AMAZON_ACCESS_KEY = 'YOUR_ACCESS_KEY'
AMAZON_SECRET_KEY = 'YOUR_SECRET_KEY'
AMAZON_ASSOCIATE_TAG = 'YOUR_ASSOCIATE_TAG'

amazon = bottlenose.Amazon(
    AMAZON_ACCESS_KEY,
    AMAZON_SECRET_KEY,
    AMAZON_ASSOCIATE_TAG,
    Region='US'
)


def check_book_formats(asin):
    try:
        response = amazon.ItemLookup(
            ItemId=asin,
            ResponseGroup='AlternateVersions,ItemAttributes',
            IdType='ASIN'
        )

        data = xmltodict.parse(response)
        item = data['ItemLookupResponse']['Items']['Item']

        title = item['ItemAttributes']['Title']
        print(f"Book Title: {title}")

        formats = {
            'Hardcover': False,
            'Paperback': False,
            'Kindle': False,
            'Audiobook': False
        }

        # Check main format
        if 'Binding' in item['ItemAttributes']:
            binding = item['ItemAttributes']['Binding']
            if binding in formats:
                formats[binding] = True

        # Check alternate versions
        if 'AlternateVersions' in item:
            alt_versions = item['AlternateVersions']['AlternateVersion']
            if isinstance(alt_versions, list):
                for version in alt_versions:
                    binding = version['Binding']
                    if binding == 'Kindle Edition':
                        formats['Kindle'] = True
                    elif binding == 'Audible Audio Edition':
                        formats['Audiobook'] = True
                    elif binding in formats:
                        formats[binding] = True
            else:
                binding = alt_versions['Binding']
                if binding == 'Kindle Edition':
                    formats['Kindle'] = True
                elif binding == 'Audible Audio Edition':
                    formats['Audiobook'] = True
                elif binding in formats:
                    formats[binding] = True

        print("Available formats:")
        for format, available in formats.items():
            print(f"{format}: {'Yes' if available else 'No'}")

    except Exception as e:
        print(f"An error occurred: {str(e)}")


# Example usage
asin = 'B00FMWWILDQ'  # Replace with your book's ASIN
check_book_formats(asin)