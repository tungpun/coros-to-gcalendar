from datetime import datetime, timedelta
import requests
import json
import schedule
import time

from config import *


@retry(tries=REQ_RETRY_TIMES, backoff=RETRY_BACKOFF, delay=RETRY_DELAY)
def get_coros_exercises(start_date = None):

    if start_date is None:
        current_date = datetime.today()
        start_date = current_date.strftime('%Y%m%d')
        date = current_date + timedelta(days=10)    # upcomming 10 days
        end_date = date.strftime('%Y%m%d')

    logger.info(f"Fetch exercises in Coros app {start_date} {end_date}")
    url = f'https://teamapi.coros.com/training/schedule/query?startDate={start_date}&endDate={end_date}&supportRestExercise=1'    
    try:
        r = requests.get(url=url, headers=COROS_HEADERS, timeout=8)
        text = r.text
        json_data = json.loads(text)
        if "message" in json_data and json_data["message"] == "Access token is invalid":
            sentry_sdk.capture_message(Exception("Coros access token is invalid already"))
            logger.error("Coros access token is invalid already")
            exit(0)
        data = json_data["data"]["entities"]
        logger.info(f"found {len(data)} activities")
    except Exception as e:
        logger.error("caught exeception in func get_coros_exercises")
        sentry_sdk.capture_exception(e)
        raise e
    return data


@retry(tries=REQ_RETRY_TIMES, backoff=RETRY_BACKOFF, delay=RETRY_DELAY)
def list_upcomming_events():
    try:
        upcomming_events = set()
        service = build("calendar", "v3", credentials=creds)

        # Call the Calendar API
        now = (datetime.utcnow() - timedelta(hours=HOURS_BUFFER_FOR_UPCOMMING)).isoformat() + "Z"	# 'Z' indicates UTC time
        events_result = (
                service.events()
                .list(
                        calendarId="primary",
                        timeMin=now,
                        maxResults=UPCOMMING_EVENTS_NO,
                        singleEvents=True,
                        orderBy="startTime",
                )
                .execute()
        )
        events = events_result.get("items", [])

        if not events:
            logger.info("No upcoming events found.")
            return

        # Prints the start and name of the next 10 events
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            upcomming_events.add(event["summary"])

        return upcomming_events

    except HttpError as error:
        logger.error(f"An error occurred: {error}")
        raise Exception(f"An error occurred: {error}")


def convert_date_format(in_coros_format):
    # convert the date in the format "20240603" to "2024-06-03"
    date_object = datetime.strptime(str(in_coros_format), "%Y%m%d")
    in_gcalendar_format = datetime.strftime(date_object, "%Y-%m-%d")
    return in_gcalendar_format


def create_event(summary, event_date):
    logger.info(f"Creating the event {summary}")
    
    service = build("calendar", "v3", credentials=creds)
    event = {
        'summary': summary,
        'description': 'A exercise in the MyProCoach Half Marathon program',
        'start': {
            'dateTime': f'{event_date}T05:45:00+07:00',
        },
        'end': {
            'dateTime': f'{event_date}T07:00:00+07:00',
            
        },
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': 10},
            ],
        },
    }

    event = service.events().insert(calendarId='primary', body=event).execute()
    logger.info('Event created: %s' % (event.get('htmlLink')))


def do_job():
    saved_upcomming_events = list_upcomming_events()
    print(saved_upcomming_events)
    for coros_exercise in get_coros_exercises():
        happen_day = coros_exercise["happenDay"]
        logger.info(f"Happen day: {happen_day}")
        exercise_summary = f"HM Training Run {happen_day}"
        if exercise_summary not in saved_upcomming_events:
            event_date = convert_date_format(happen_day)
            create_event(summary=exercise_summary, event_date=event_date)
        else:
            logger.info(f"Skip {exercise_summary} because it is duplicated!")



if __name__ == "__main__":
    do_job()
    logger.info("Scheduling...")

    schedule.every().hour.do(do_job)

    while True:
        # Run pending tasks if there are any
        schedule.run_pending()
        time.sleep(1)
