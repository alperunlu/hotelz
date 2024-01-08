import csv 
import requests  
from lxml import html  

def get_user_input():
    city = input("City name: ")
    check_in = input("Check-in date (YYYY-MM-DD): ")
    check_out = input("Check-out date (YYYY-MM-DD): ")
    return city, check_in, check_out

def get_response(city, check_in, check_out):
    url = "https://www.booking.com/searchresults.html"

    headers = {
        "authority": "www.booking.com",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "max-age=0",
        "referer": "https://www.booking.com/",
        "sec-ch-ua": '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    }

    params = {
        "ss": f"{city}",
        "lang": "en-us",
        "dest_type": "city",
        "ac_langcode": "en",
        "search_selected": "true",
        "checkin": f"{check_in}",
        "checkout": f"{check_out}",
        "group_adults": "1",
        "no_rooms": "1",
        "group_children": "0",
        "sb_travel_purpose": "leisure",
        "selected_currency": "USD",
    }

    response = requests.get(url=url, headers=headers, params=params)
    return response

def parse_response(response):
    parser = html.fromstring(response.text)
    hotels_data = []
    hotels_list = parser.xpath("//div[@data-testid='property-card']")
    for hotel in hotels_list:
        name = hotel.xpath(".//div[@data-testid='title']/text()")
        location = hotel.xpath(".//span[@data-testid='address']/text()")
        price = hotel.xpath(".//span[@data-testid='price-and-discounted-price']//text()")
        rating = hotel.xpath(".//div[@data-testid='review-score']/div[contains(@aria-label, 'Scored')]/text()")
        review_count = hotel.xpath(".//div[@class='abf093bdfe f45d8e4c32 d935416c47']/text()")

        # website = hotel.xpath(".//a[@data-ga-track='clickout']//@href")
        # phone_number = hotel.xpath(".//span[@class='phone-number']//text()")

        hotel_data = {
            "name": clean_str(name),
            "location": clean_str(location),
            "price": clean_str(price),
            "rating": clean_str(rating),
            "review_count": clean_review_count(review_count),
        #    "website": clean_str(website),
        #    "phone_number": clean_str(phone_number),
        }
        hotels_data.append(hotel_data)

    return hotels_data

def clean_str(raw_string):
    clean_str = " ".join(" ".join(raw_string).split()).strip() if raw_string else None
    return clean_str

def clean_review_count(raw_review):
    clean_review = clean_str(raw_review)
    review_count = (
        clean_review.replace("reviews", "")
        .replace("review", "")
        .replace(",", "")
        .strip()
        if clean_review
        else None
    )
    return review_count

def save_data(data):
    if not data:
        return
    fields = data[0].keys()
    with open("Hotels.csv", "w", newline='', encoding='utf-8') as file:
        dict_writer = csv.DictWriter(file, fields)
        dict_writer.writeheader()
        dict_writer.writerows(data)

def main():
    city, check_in, check_out = get_user_input()

    response = get_response(city, check_in, check_out)

    if response.status_code == 200:
        data = parse_response(response)
        save_data(data)
    else:
        print("Invalid response.")

if __name__ == "__main__":
    main()
