def probe():
    import cloudscraper
    from bs4 import BeautifulSoup

    scraper = cloudscraper.create_scraper()
    print("Fetching HLTV results...")
    url = "https://www.hltv.org/results?stars=3"
    try:
        response = scraper.get(url)
        print("Status code:", response.status_code)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            results = soup.find_all('div', class_='result-con')
            print(f"Found {len(results)} matches.")
            if results:
                match = results[0]
                a_tag = match.find('a', class_='a-reset')
                if a_tag:
                    href = a_tag.get('href')
                    print(f"First match link: https://www.hltv.org{href}")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    probe()
