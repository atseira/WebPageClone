from urllib.parse import urlparse, urljoin
from pathlib import Path
from urllib3.exceptions import InsecureRequestWarning
from urllib3 import disable_warnings
from bs4 import BeautifulSoup
import re, html
import requests
import os
import validators
import logging
import threading
import json


lock = threading.Lock()
threads = []

disable_warnings(InsecureRequestWarning)

def read_file(filename):
	try:
		with open(filename, 'r', errors='ignore') as f:
			data = f.read()
		return data

	except Exception as ex:
		logging.error("Error opening or reading input file: {}", ex)
		exit()

def remove_dir(directory):
    try:
        directory = Path(directory)
        for item in directory.iterdir():
            if item.is_dir():
                remove_dir(item)
            else:
                item.unlink()
        directory.rmdir()
    except Exception as ex: # Ex always the exception :(
        None

def create_dir(path):
    try:
        os.makedirs(path, exist_ok = True)
    except OSError as error:
        logging.error("Failed creating dir {}", path)

def normalize_path(path):
    return path.replace("\\", "/")

def clean_path(path):
    path = normalize_path(path)
    if len(path) > 2:
        if path[:2] == "./":
            return path[2:]

    return path

def dont_slash(path):
    if len(path) > 0:
        if path[0] in ['/', '\\']:
            return path[1:]
    return path

def get_content(url, max_retry=2):
    if max_retry == 0: return None
    try:
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'no-cache',
            'dnt': '1',
            'pragma': 'no-cache',
            'sec-ch-ua': '"Google Chrome";v="111", "Not(A:Brand";v="8", "Chromium";v="111"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36',
        }
        req = requests.get(url, headers=headers, timeout=5, verify=False)
        return req
    except Exception as ex:
        logging.error("{} >> {}", url, ex)
        get_content(url, max_retry-1)
    
    return None

def get_file_name(spath):
    url_path = urlparse(spath).path
    file_name = url_path[url_path.rfind("/")+1:]
    if url_path.rfind(".") == -1: file_type = "file";
    else: file_type = url_path[url_path.rfind(".")+1:]; file_name = file_name[:file_name.rfind(".")]
    
    if file_name == "": file_name = "UNKNOWN"
    for forbiden_char in "\ / : * ? \" ' < > |".split(" "):
        if forbiden_char in file_type:
            file_type = "file"
            break
    
    for forbiden_char in "\ / : * ? \" ' < > |".split(" "):
        if forbiden_char in file_name:
            file_name = file_name.replace(forbiden_char, "_")

    if len(file_name) > 255:
        file_name = "name_too_long"

    return file_name, file_type

def download_local_asset(saved_path, base_url, file_path, asset, assets_list, thread_id):
    # Calculate saved asset name
    asset["saved_to"] = normalize_path(f"assets/{asset['name']}-{thread_id}.{asset['type']}")

    # Fix path from current edited file_src
    with lock:
        old_content = read_file(f"{saved_path}/{asset['source']['file']}")
    
        replacement = asset["saved_to"]
        if asset["source"]["file"].count("/") > 0: replacement = asset["saved_to"][len("assets/"):]
        new_content = old_content.replace(asset["source"]["replace"], asset["source"]["replace"].replace(asset["path"], replacement))
        
        with open(normalize_path(f"{saved_path}/{asset['source']['file']}"), "w") as f: f.write(new_content)

    logging.info(">> Downloading asset {}", asset["url"])
    req = get_content(asset["url"])
    if req == None:
        logging.error(f">> {asset['url']} Failed")
        return

    asset["status_code"] = req.status_code
    if req != None and req.status_code == 200:
        logging.info(">> Saving asset to {}", asset['saved_to'])
        with open(normalize_path(f"{saved_path}/{asset['saved_to']}"), "wb") as f: f.write(req.content)

        # LOGS TO assets/assets_info.txt
        with lock:
            with open(normalize_path(f"{saved_path}/assets/assets_info.txt"), "a") as f: f.write(f"{asset['saved_to']} => {asset['url']}\n")

        # CHECK IF ASSET IS CSS AND HAS LOCAL URL
        if asset['type'] == "css":
            matches = re.finditer(r"(?<=url\().*?(?=\))", req.text, re.MULTILINE)
            css_asset_list = []
            for match in matches:
                css_url = match.group()
                css_url_unescaped = html.unescape(css_url)
                if len(css_url_unescaped) <= 2: continue

                css_localcontent_url = css_url_unescaped
                if css_url_unescaped[0]+css_url_unescaped[-1] in ['""', "''"]:
                    css_localcontent_url = css_url_unescaped[1:-1]
                
                if "data:image/" in css_localcontent_url:continue

                if len(css_localcontent_url) >= 2:
                    css_localcontent_url = clean_path(css_localcontent_url)
                    css_asset_list.append({"path":css_localcontent_url, "source":{"file":asset["saved_to"],"replace":css_url}})

            for i in range(len(css_asset_list)):
                if i >= len(css_asset_list): break

                css_asset = css_asset_list[i]

                if "status_code" in css_asset.keys(): continue
                # Converting assets to full url

                parsed = urlparse(asset["url"])
                css_file_path = os.path.normpath(parsed.path[:parsed.path.rfind("/")+1]).replace("\\", "/") + "/"

                asset_fullurl = css_asset['path']
                if css_asset['path'][:2] == "//":
                    asset_fullurl = urlparse(base_url).scheme + ":" + css_asset['path']
                elif urlparse(css_asset['path']).scheme == "":
                    if css_asset['path'][0] in ['/', '\\']:
                        asset_fullurl = normalize_path(urljoin(base_url, css_asset['path']))
                    else:
                        asset_fullurl = normalize_path(urljoin(urljoin(base_url, css_file_path), css_asset['path']))
                
                css_asset["source"]["url"] = asset["url"]
                css_asset["url"] = asset_fullurl
                css_asset["name"], css_asset["type"] = get_file_name(asset_fullurl)                        

                if validators.url(css_asset["url"]):
                    t = threading.Thread(target=download_local_asset, args=(saved_path, base_url, css_file_path, css_asset, assets_list, f"{thread_id}{i}"))
                    threads.append(t)
                    t.start()
                else:
                    css_asset_list.remove(css_asset)

                assets_list.append(css_asset)

def save_webpage(url, html_content="", saved_path="result"):
    global threads
    logging.info("SAVING {}", url)

    remove_dir(saved_path)
    create_dir(saved_path)
    create_dir(normalize_path(saved_path+"/assets"))

    threads = []

    if html_content == "": html_content = get_content(url).text

    # Write HTML to original.html
    with open(normalize_path(saved_path+"/original.html"), "w", encoding='utf-8') as f: f.write(html_content)

    # checking if html dom has <base>
    soup = BeautifulSoup(html_content, 'html.parser')

    # check if <base> tag exists
    base_tag = soup.find('base')
    if base_tag is not None:
        # get the 'href' attribute value
        base_href = base_tag.get('href')

        # check if the href value is a full URL or a partial URL
        if bool(urlparse(base_href).netloc):
            # if the href value is a full URL, use it directly as the absolute URL path
            url = base_href
        else:
            # if the href value is a partial URL, construct the absolute URL path using urlparse and urljoin
            currenturl_parse = urlparse(url)
            base_parse = urlparse(base_href)

            base_path = base_parse.path if base_parse.netloc else base_parse.path.lstrip('/')
            url = urljoin(currenturl_parse.scheme + '://' + currenturl_parse.netloc, base_path)

        # remove base tag
        base_tag.decompose()
    
        html_content = soup.prettify()

    parsed = urlparse(url)
    base_url = parsed.scheme + "://" + parsed.netloc + "/"
    file_path = os.path.normpath(parsed.path[:parsed.path.rfind("/")+1]).replace("\\", "/") + "/"
    if len(file_path) > 0: file_path = file_path[1:]

    # Write HTML first
    with open(normalize_path(saved_path+"/index.html"), "w", encoding='utf-8') as f: f.write(html_content)
    html_tag_cssjs = { "link" : "href", "script" : "src", "img":"src" }

    # Collect assets
    assets_list = []
    for tag in html_tag_cssjs.keys():
        pattern = fr"(?<=<{tag}).*?(?=>)"
        matches = re.finditer(pattern, html_content, re.MULTILINE)
        for match in matches:
            attr=html_tag_cssjs[tag]
            
            tag_attr = match.group()
            pattern2 = rf"(?<={attr}=(\"|')).*?(?=(\"|'))"
            matches2 = re.finditer(pattern2, tag_attr, re.MULTILINE)

            for match2 in matches2:
                asset_path = match2.group()
                lquote = match2.group(1)
                rquote = match2.group(2)

                replace = f"{lquote}{asset_path}{rquote}"
                # DOWNLOAD ASSET IF LOCAL ASSET
                if len(asset_path) >= 2:
                    asset_path = clean_path(asset_path)
                    assets_list.append({"path":asset_path, "source":{"file":normalize_path("index.html"),"replace":replace}})
    
    # Also download from inline css
    pattern = r"(?<=url\().*?(?=\))"
    matches = re.finditer(pattern, html_content, re.MULTILINE)

    for match in matches:
        css_url = match.group()
        css_url_unescaped = html.unescape(css_url)
        if len(css_url_unescaped) <= 2: continue

        css_localcontent_url = css_url_unescaped
        if css_url_unescaped[0]+css_url_unescaped[-1] in ['""', "''"]:
            css_localcontent_url = css_url_unescaped[1:-1]
        
        if "data:image/" in css_localcontent_url:continue

        if len(css_localcontent_url) >= 2:
            css_localcontent_url = clean_path(css_localcontent_url)
            assets_list.append({"path":css_localcontent_url, "source":{"file":normalize_path("index.html"),"replace":css_url}})

    for i in range(len(assets_list)):
        if i >= len(assets_list): break
        asset = assets_list[i]
        if "status_code" in asset.keys(): continue
        # Converting assets to full url
        asset_fullurl = asset["path"]
        if asset["path"][:2] == "//":
            asset_fullurl = urlparse(base_url).scheme + ":" + asset["path"]
        elif urlparse(asset["path"]).scheme == "":
            if asset["path"][0] in ['/', '\\']:
                asset_fullurl = normalize_path(urljoin(base_url, asset["path"]))
            else:
                asset_fullurl = normalize_path(urljoin(urljoin(base_url, file_path), asset["path"]))
        
        asset["url"] = asset_fullurl
        asset["source"]["url"] = base_url+"index.html"
        # Get filetype
        asset["name"], asset["type"] = get_file_name(asset_fullurl)

        if validators.url(asset["url"]):
            t = threading.Thread(target=download_local_asset, args=(saved_path, base_url, file_path, asset, assets_list, f"{i}"))
            threads.append(t)
            t.start()
        else:
            assets_list.remove(asset)
    
    # wait for all threads to finish
    for t in threads:
        t.join()

    # save assets.json
    new_assets = []
    for asset in assets_list:
        if asset.get("url") != None and asset.get("saved_to") != None:
            if os.path.exists(f"{saved_path}/{asset['saved_to']}") == False:
                continue

            new_assets.append({
                "url": asset["url"],
                "download_status_code": asset.get("status_code"),
                "saved_to": asset.get("saved_to"),
                "source": {
                    "file": asset["source"]["file"],
                    "url": asset["source"]["url"]
                },
            })

    with open(saved_path+"/assets.json", "w") as f:
        json.dump(new_assets, f, indent=4, sort_keys=True)

    assets_ok = [x for x in assets_list if "status_code" in x.keys() and x['status_code'] == 200]
    if len(assets_list) == 0: return 1.0
    return float(len(assets_ok)/len(assets_list))

def save_html(url, html_content="", saved_path="result"):
    logging.info("SAVING HTML {}", url)
    remove_dir(saved_path)
    create_dir(saved_path)
    create_dir(normalize_path(saved_path+"/assets"))

    if html_content == "": html_content = get_content(url).text
    
    # Write HTML first
    html_file = normalize_path(saved_path+"/index.html")
    with open(html_file, "w", encoding='utf-8') as f: f.write(html_content)

    soup = BeautifulSoup(html_content, "html.parser")

    # find all HTML elements with an "src" or "href" attribute
    elements = soup.find_all(["img", "link", "script"])

    for element in elements:
        # get the value of the "src" or "href" attribute
        source_url = element.get("src") or element.get("href")

        # check if the URL is relative
        if source_url and not urlparse(source_url).netloc:
            # construct the full URL using the base URL of the HTML page
            full_url = urljoin(url, source_url)

            # replace the relative URL with the full URL
            if element.get("src"):
                element["src"] = full_url
            elif element.get("href"):
                element["href"] = full_url

    # save the modified HTML file
    with open(html_file, "w") as file:
        file.write(str(soup))