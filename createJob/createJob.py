#!/usr/bin/env python
import os
import logging
import jsonpickle
import boto3
from botocore.exceptions import ClientError
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all
import s3util
import sqsutil
import jobstable


logger = logging.getLogger()
logger.setLevel(logging.INFO)
patch_all()


def preamble(event, context):
    logger.info('## ENVIRONMENT VARIABLES\r' + jsonpickle.encode(dict(**os.environ)))
    logger.info('## EVENT\r' + jsonpickle.encode(event))
    logger.info('## CONTEXT\r' + jsonpickle.encode(context))
    client = boto3.client('lambda')
    account_settings = client.get_account_settings()
    print(account_settings['AccountUsage'])
    return True


def parse_event_record(event_record):
    global job_tool
    global job_source
    global submitter_id
    global submit_timestamp

    event_body = eval(event_record['body'])
    if event_body is None:
        print('parse_event: event body is missing.')
        return False

    job = event_body['job']
    if job is None:
        print('parse_event: job is missing.')
        return False

    job_tool = job['job_tool']
    if job_tool is None:
        print('parse_message: job tool is missing.')
        return False

    job_source = job['job_source']
    if job_source is None:
        print('parse_message: job source is missing.')
        return False

    event_attributes = event_record['attributes']
    if event_attributes is None:
        print('parse_event: event attributes are missing.')
        return False

    submitter_id = event_attributes['SenderId']
    if submitter_id is None:
        print('parse_event: sender id is missing.')
        return False

    submit_timestamp = event_attributes['SentTimestamp']
    if submit_timestamp is None:
        print('parse_event: sent timestamp is missing.')
        return False

    # success
    return True


def send_message(queue_name, item):
    # get queue url
    sqsutil.list_queues()
    queue_url = sqsutil.get_queue_url(queue_name)
    if queue_url is None:
        print(f'send_message: Queue {queue_name} does not exist.')
        return False

    # send message
    message_body = {
        "action": "process",
        "job": {
            "job_id": item['job_id'],
            "job_tool": item['job_tool'],
            "job_source": item['job_source']
        }
    }
    message_id = sqsutil.send_message(queue_url, str(message_body))
    print(f'MessageId: {message_id}')
    print(f'MessageBody: {message_body}')

    # debug: receive message
    message = sqsutil.receive_message(queue_url)
    if message is None:
        print(f'send_message: cannot retrieve sent messge.')
        return False
    print('Received message:')
    print(message)

    # success
    return True


# createJob handler
def createJob(event, context):
    success = preamble(event, context)
    if not success:
        print('preamble failed. Exit.')
        return False

    # get jobs table
    jobs_table = jobstable.get_jobs_table()
    if jobs_table is None:
        print('get_jobs_table failed.  Exit.')
        return False

    # create jobs record
    event_records = event['Records']
    for event_record in event_records:
        # debug: print event record
        print('Event record:')
        print(event_record)

        # parse event record
        success = parse_event_record(event_record)
        if not success:
            print('parse_event_record failed.  Next.')
            continue

        # debug: print job record attributes
        print('Job record attributes:')
        print(f'job_tool: {job_tool}')
        print(f'job_source: {job_source}')
        print(f'submitter_id: {submitter_id}')
        print(f'submit_timestamp: {submit_timestamp}')

        # create job record
        job_id = jobstable.create_job_record(jobs_table, job_tool, job_source, submitter_id, submit_timestamp)
        if job_id is None:
            print('create_job_record failed.  Next.')
            continue

        # debug: get and print job record
        item = jobstable.get_job_record(jobs_table, job_id)
        if item is None:
            print('get_job_record failed.  Next.')
            continue
        print('Job record:')
        print(item)

        # set process job queue name
        queue_name = 'jobs-list-process-job-queue-rwang5688'
        if 'PROCESS_JOB_QUEUE' in os.environ:
            queue_name = os.environ['PROCESS_JOB_QUEUE']

        # send job context to process job queue
        success = send_message(queue_name, item)
        if not success:
            print('send_message failed.  Next.')
            continue

        # TO DO:
        # Start ECS task to process job!!!

        # update job status
        job_status = "started"
        job_logfile = ""
        success = jobstable.update_job_status(jobs_table, job_id, job_status, job_logfile)
        if not success:
            print('update_job_status failed.  Next.')
            continue

    # success
    return True


# main function for testing createJob handler
def main():
    xray_recorder.begin_segment('main_function')
    file = open('event.json', 'rb')
    try:
        # read sample event
        ba = bytearray(file.read())
        event = jsonpickle.decode(ba)
        logger.warning('## EVENT')
        logger.warning(jsonpickle.encode(event))
        # create sample context
        context = {'requestid': '1234'}
        # invoke handler
        result = createJob(event, context)
        # print response
        print('## RESPONSE')
        print(str(result))
    finally:
        file.close()
    file.close()
    xray_recorder.end_segment()


if __name__ == '__main__':
    main()

