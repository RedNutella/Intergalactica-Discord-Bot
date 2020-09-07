import datetime

def convert_to_date(argument):
    text = argument

    if text.count("-") == 2:
        dates = [int(x) for x in text.split("-")]
    elif text.count("/") == 2:
        dates = [int(x) for x in text.split("/")]
    elif text == "today":
        return datetime.datetime.now().date().strftime("%Y-%m-%d")
    else:
        return None

    if dates[1] > 12:
        return None

    if len(str(dates[0])) == 4:
        year,month,day = dates
    else:
        day,month,year = dates

    return datetime.date(year, month, day)
