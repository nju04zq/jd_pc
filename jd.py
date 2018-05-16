#/usr/bin/env python
# encoding: utf-8

import os
import re
import bs4
import sys
import json
import time
import codecs
import shutil
import datetime
import requests
import unicodedata
from selenium import webdriver
from optparse import OptionParser

jd_link = "https://item.jd.com/{gid}.html"
jd_price_link = "http://pe.3.cn/prices/mgets?skuids={gid}"

input_json_fname = "input.json"
data_json_fname = "data.json"
report_fname = "report.md"

with_update = False
with_graph = False
update_ts = None

def chr_width(c):
    if (unicodedata.east_asian_width(c) in ('F','W','A')):
        return 2
    else:
        return 1

def str_width(s):
    s = unicode(s)
    width = 0
    for ch in s:
        width += chr_width(ch)
    return width

def trim_str(s, width):
    s = unicode(s)
    cur_width, i = 0, 0
    for ch in s:
        cur_width += chr_width(ch)
        if cur_width >= width:
           break 
        i += 1
    return s[:i+1]

class Item(object):
    def __init__(self, val):
        self.in_suite = val["suite"]
        self.type = val["type"]
        self.name = val["name"]
        self.link = val["link"]
        self.gid = get_gid(self.link)
        self.lowest = val["lowest"]
        if "prices" in val:
            self.prices = self.format_prices(val["prices"])
        else:
            self.prices = []

    def format_prices(self, prices):
        prices_fmt = self.format_multiple_prices(prices)
        prices_fmt.sort(key=lambda x:x[0])
        return prices_fmt

    def format_multiple_prices(self, prices):
        prices_fmt = []
        for p in prices:
            prices_fmt.append((p["time"], p["val"]))
        return prices_fmt

    def add_price(self, price):
        if len(self.prices) == 0 or price != self.prices[-1][1]:
            self.prices.append((update_ts, price))
            self.lowest = min(self.prices[-1][1], self.lowest)

    def to_kv(self):
        kv = {}
        kv["suite"] = self.in_suite
        kv["type"] = self.type
        kv["name"] = self.name
        kv["link"] = self.link
        kv["lowest"] = self.lowest
        prices = []
        for p in self.prices:
            prices.append({"time":p[0], "val":p[1]})
        kv["prices"] = prices
        return kv

    def brief_tbl_line(self):
        line = [self.type, str(self.lowest), str(self.prices[-1][1])]
        return line

    def get_price_plot_data(self):
        all_ts = [datetime.datetime.fromtimestamp(price_info[0]) \
                  for price_info in self.prices]
        prices = [price_info[1] for price_info in self.prices]
        all_price = [float(p)/min(prices) for p in prices]
        return (all_ts, all_price)

    def __repr__(self):
        vals = []
        vals.append(str(self.in_suite))
        vals.append(str(self.type))
        vals.append(str(self.name))
        vals.append(str(self.link))
        vals.append(str(self.lowest))
        vals.append(str(self.prices))
        return "\n".join(vals) + "\n"

def get_gid(link):
    ptn = jd_link.replace(".", "\\.").format(gid="(\\d+)")
    res = re.findall(ptn, link)
    if len(res) == 0:
        raise Exception("link {0} not recognized".format(link))
    try:
        gid = int(res[0])
    except:
        raise Exception("fail to get gid from {0}".format(res[0]))
    return gid

def get_page(link):
    chrome_options = webdriver.chrome.options.Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(chrome_options=chrome_options)
    driver.get(link)
    return driver.page_source

def get_price_selenium(gid):
    link = jd_link.format(gid=gid)
    page_text = get_page(link)
    soup = bs4.BeautifulSoup(page_text, "html.parser")
    res = soup.find_all("span", class_="price J-p-4466792")
    if len(res) == 0:
        raise Exception("price tag not found for {0}".format(link))
    elif len(res) > 1:
        raise Exception("multiple price tag found for {0}".format(link))
    price_text = res[0].text
    try:
        price = float(price_text)
    except:
        raise Exception("price {0} not valid for {1}".format(price_text, link))
    return int(price)

def get_price_api(gid):
    link = jd_price_link.format(gid=gid)
    r = requests.get(link)
    resp = json.loads(r.text)
    try:
        price_text = resp[0]["p"]
        price = float(price_text)
    except:
        raise Exception("price not valid for {0}, resp {1}".format(link,r.text))
    return int(price)

def get_price(gid):
    use_api = True
    if use_api:
        return get_price_api(gid)
    else:
        return get_price_selenium(gid)

def read_items_from(fname):
    with codecs.open(fname, "r", encoding="utf-8") as fp:
        content = fp.read()
    item_vals = json.loads(content, encoding="utf-8")
    items, types = [], set()
    for item_val in item_vals:
        item = Item(item_val) 
        items.append(item)
        if item.type in types:
           raise Exception("Type {0} has multiple items".format(item.type))
        else:
            types.add(item.type)
    items.sort(key=lambda x:int(x.in_suite), reverse=True)
    return items

def read_input():
    if os.path.exists(data_json_fname):
        return read_items_from(data_json_fname)
    else:
        return read_items_from(input_json_fname)

def save_items(items):
    if os.path.exists(data_json_fname):
        shutil.copyfile(data_json_fname, data_json_fname+".bk")
    vals = []
    for item in items:
        vals.append(item.to_kv())
    with codecs.open(data_json_fname, "w", encoding="utf-8") as fp:
        fp.write(json.dumps(vals, indent=2,ensure_ascii=False,encoding="utf-8"))

def calc_prices(items):
    suite_prices, total_prices = [], []
    idxs = [0 for i in xrange(len(items))]
    while True:
        suite_price, total_price, ts = 0, 0, sys.maxint
        for i, item in enumerate(items):
            if idxs[i] >= len(item.prices):
                price_info = item.prices[-1]
            else:
                price_info = item.prices[idxs[i]]
                ts = min(ts, price_info[0])
            total_price += price_info[1]
            if item.in_suite:
                suite_price += price_info[1]
        if ts == sys.maxint:
            break
        suite_prices.append((ts, suite_price))
        total_prices.append((ts, total_price))
        updated = 0
        for i, item in enumerate(items):
            if idxs[i] < len(item.prices) and item.prices[idxs[i]][0] == ts:
                idxs[i] += 1
                updated += 1
        if updated == 0:
            break
    return suite_prices, total_prices

def make_report(items):
    suite_prices, total_prices = calc_prices(items)
    make_brief_report(items, suite_prices, total_prices)
    make_html_report(items, suite_prices, total_prices)
    if with_graph:
        make_graph(items, suite_prices, total_prices)

class PrettyTable(object):
    def __init__(self, header, lines):
        self.header = header
        self.lines = lines
        self.col_limit = self.get_table_col_limit()
        # pad the seperator between columns
        self.col_seperator = "  "

    # print the whole table
    def show(self):
        sys.stdout.write(self.format())

    # format the whole table, return string
    def format(self):
        output = ""
        output += self.format_table_one_line(self.header)
        output += self.format_table_seperator()
        for oneline in self.lines:
            output += self.format_table_one_line(oneline)
        return output

    # calculate the width limit for each column in table
    def get_table_col_limit(self):
        self.lines.append(self.header)
        col_cnt = len(self.header)
        col_limit = [0 for i in xrange(col_cnt)]
        for line in self.lines:
            if len(line) != col_cnt:
                raise Exception("Table line {0} not match header {1}".format(\
                                line, self.header))
            for i in xrange(len(col_limit)):
                col_limit[i] = max(col_limit[i], len(line[i]))
        self.lines.pop()
        return col_limit

    # format one line in the table, each line is defined by a tuple containing
    # column values. If column value string length is less than the column width
    # limit, extra spaces will be padded
    def format_table_one_line(self, line):
        output = ""
        cols = []
        for i in xrange(len(line)):
            s = ""
            s += line[i]
            s += (" " * (self.col_limit[i]-len(line[i])))
            cols.append(s)
        output += (self.col_seperator.join(cols) + "\n")
        return output

    # format the seperator as -------
    def format_table_seperator(self):
        sep_cnt = sum(self.col_limit)
        # count in column seperators, why -1?, 2 columns only have one
        sep_cnt += (len(self.col_limit) - 1)*len(self.col_seperator)
        # one extra sep to make it pretty
        sep_cnt += 1
        return "-" * sep_cnt + "\n"

def make_brief_report(items, suite_prices, total_prices):
    header = ["type", "lowest", "current"]
    lines = []
    for item in items:
        lines.append(item.brief_tbl_line())
    prices = [p[1] for p in total_prices]
    lines.append(["TOTAL", str(min(prices)), str(prices[-1])])
    prices = [p[1] for p in suite_prices]
    lines.append(["SUITE", str(min(prices)), str(prices[-1])])
    tbl = PrettyTable(header, lines)
    tbl.show()

class MDTable(object):
    COL_SEP = " | "

    def __init__(self, header, lines):
        self.header = header
        self.lines = lines

    def embrace(self, s):
        return "| " + s + " |"

    def format_header(self):
        s = self.COL_SEP.join(self.header)
        return self.embrace(s) + "\n"

    def format_seperator(self):
        seps = ["----" for i in xrange(len(self.header))]
        s = self.COL_SEP.join(seps)
        return self.embrace(s) + "\n"

    def format_one_line(self, line):
        s = self.COL_SEP.join(line)
        return self.embrace(s) + "\n"

    def format(self):
        out = ""
        out += self.format_header()
        out += self.format_seperator()
        for line in self.lines:
            out += self.format_one_line(line)
        return out + "\n\n"

    def show(self):
        sys.stdout.write(self.format())

def md_link(text, link):
    return "[{text}]({link})".format(text=text, link=link)

def make_html_report(items, suite_prices, total_prices):
    header = ["名称", "当前价", "最低价"]
    lines = []
    for item in items:
        name = md_link(trim_str(item.name, 60), item.link)
        lines.append((name, str(item.prices[-1][1]),str(item.lowest)))
    prices = [p[1] for p in total_prices]
    lines.append(["总计", str(prices[-1]), str(min(prices))])
    prices = [p[1] for p in suite_prices]
    lines.append(["套装", str(prices[-1]), str(min(prices))])
    md = MDTable(header, lines)
    with open(report_fname, "w") as fp:
        fp.write(md.format())

def make_plot_data(prices):
    d = datetime.timedelta(days=1)
    now = int(time.time())
    now_date = datetime.date.fromtimestamp(now)
    cur = datetime.date.fromtimestamp(prices[0][0])
    prices += [(now, prices[-1][1])]
    i, all_ts, all_price = 0, [], []
    while i < len(prices):
        price_info = prices[i]
        thisday = datetime.datetime.fromtimestamp(price_info[0])
        thisdate = datetime.date.fromtimestamp(price_info[0])
        if thisdate <= cur:
            all_ts.append(thisday)
            all_price.append(price_info[1])
            i += 1
        else:
            ts = datetime.datetime(cur.year, cur.month, cur.day, 12, 0, 0)
            all_ts.append(ts)
            all_price.append(prices[i-1][1])
        if thisdate >= cur:
            cur += d
    min_price = min(all_price)
    all_price = [float(p)/min_price for p in all_price]
    return (all_ts, all_price)

def make_graph(items, suite_prices, total_prices):
    import matplotlib.pyplot as plt
    import numpy as np
    import seaborn as sns

    data = {}
    for item in items:
        data[item.type] = make_plot_data(item.prices)
    data["Total"] = make_plot_data(total_prices)
    grid_size = 5
    # plot
    sns.set_style("darkgrid")
    fig = plt.figure()
    # 1x1 grid, the 1st one
    keys, i, j = data.keys(), 0, 1
    while i < len(keys):
        start, end = i, min(len(keys), i+grid_size)
        ax = fig.add_subplot(2, 2, j)
        while start < end:
            key = keys[start]
            ax.plot(data[key][0], data[key][1], label=key)
            start += 1
        ax.legend(loc="upper right")
        ax.set_ylabel("Ratio")
        ax.set_xlabel("Time")
        i += grid_size
        j += 1
    plt.show()

def update(items):
    global update_ts
    update_ts = int(time.time())
    for i, item in enumerate(items):
        if sys.stdout.isatty():
            sys.stdout.write("\r[{0}/{1}]".format(i+1, len(items)))
            sys.stdout.flush()
        price = get_price(item.gid)
        item.add_price(price)
    if sys.stdout.isatty():
        sys.stdout.write("\n")

def summary():
    items = read_input()
    if with_update:
        update(items)
        save_items(items)
    make_report(items)

def parse():
    parser = OptionParser()
    parser.set_defaults(with_graph=False)
    parser.set_defaults(with_update=False)
    parser.add_option("--graph", action="store_true", dest="with_graph",
                      help="Run with graph")
    parser.add_option("--update", action="store_true", dest="with_update",
                      help="Run with update")
    options, args = parser.parse_args()
    global with_update, with_graph
    with_update = options.with_update
    with_graph = options.with_graph

def main():
    reload(sys)
    sys.setdefaultencoding("utf-8")
    parse()
    summary()

if __name__ == "__main__":
    main()
