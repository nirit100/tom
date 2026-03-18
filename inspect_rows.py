from playwright.sync_api import sync_playwright

def main():
    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        q = 'Tom und das Erdbeermarmeladebrot mit Honig'
        url = f'https://mediathekviewweb.de/#query={q.replace(" ","%20")}&page=1'
        print('Loading', url)
        page.goto(url, timeout=60000)
        page.wait_for_selector('table tbody tr', timeout=60000)
        rows = page.query_selector_all('table tbody tr')
        print('Rows found:', len(rows))
        for i,row in enumerate(rows[:10]):
            print('\n=== ROW', i, '===')
            try:
                print('RAW:', repr(row.inner_text()))
                tds = row.query_selector_all('td')
                print('TD count:', len(tds))
                for j,td in enumerate(tds):
                    txt = td.inner_text().strip()
                    print('TD', j, ':', repr(txt))
                    anchors = td.query_selector_all('a')
                    for a in anchors:
                        href = a.get_attribute('href')
                        a_txt = a.inner_text().strip()
                        print('  A =>', repr(a_txt), href)
            except Exception as e:
                print('  error reading row', e)
        browser.close()
    finally:
        p.stop()

if __name__ == '__main__':
    main()
