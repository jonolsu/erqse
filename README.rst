.. image:: https://www.erockhold.com/wp-content/uploads/2016/10/logo-2.png
    :target: https://enchantedrock.com/


Enchanted Rock ERCOT QSE Python Utilities
===============================


This Python library contains general utilities helpful for ERCOT Qualified Scheduling Entities:
::

$ GIT_SSH_COMMAND='ssh -i ~/.ssh/your_rsa_key' pip install git+ssh://git@github.com/jonolsu/erqse.git@main

To extract the certificate and private key from the .pfx:

.. code-block:: shell

     openssl pkcs12 -info -in '.\0787579852300$API_MoteSQ3JBennett.pfx' -out cert.pem -nokeys
     openssl pkcs12 -info -in '.\0787579852300$API_MoteSQ3JBennett.pfx' -out privkey.pem -nocerts -nodes

The private key must be unencrypted. See https://requests.readthedocs.io/en/latest/user/advanced/#client-side-certificates

Examples
========

.. code-block:: python

    client = erqse.ErcotClient(
        wsdl_url="erqse/wsdl/Nodal.wsdl",
        endpoint_url="https://testmisapi.ercot.com/2007-08/Nodal/eEDS/EWS/", # ercot_credentials["ENDPOINT_ADDRESS"],
        participantId="QELEC3", # ercot_credentials["PARTICIPANT_ID"],
        userId="API_MoteSQ3JBennett", # ercot_credentials["USER_ID"],
        cert_filename="cert.pem",
        key_filename="privkey.pem"
    )

    selfschedule_bidset_data = {
        "tradingDate": "2023-07-01",
        "submitTime": datetime.now(),
        "SelfSchedule": {
            "startTime": "2023-06-01T00:06:00-05:00",
            "endTime":   "2023-06-02T00:06:00-05:00",
            "source": "some_source",
            "sink": "some_sink",
            "EnergySchedule": {
                "startTime": None,
                "endTime": None,
                "TmPoint": [
                    {
                        "time":   "2023-06-01T06:00:00-05:00",
                        "ending": "2023-06-01T18:00:00-05:00",
                        "value1": 1234
                    },
                    {
                        "time":   "2023-06-01T18:00:00-05:00",
                        "ending": "2023-06-02T06:00:00-05:00",
                        "value1": 5678
                    }
                ]
            }
        }
    }

    result = client.self_schedule_submit(selfschedule_bidset_data)
    pprint(result)

::

    {'response': {
        'Header': {
            'Verb': 'reply',
            'Noun': 'BidSet',
            'ReplayDetection': {
                'Nonce': {
                    '_value_1': 'd283f4c4fbccb5c83d0ca6f74be90700',
                    'Id': None,
                    '_attr_1': None,
                    'EncodingType': None
                },
                'Created': {
                    '_value_1': '2023-06-05T00:56:39.657-05:00',
                    'Id': None,
                    '_attr_1': None
                }
            },
            'Revision': '001',
            'Source': 'ERCOT',
            'UserID': 'API_MoteSQ3JBennett',
            'MessageID': '65346596975777638572818911445427198429',
            'Comment': None,
            '_value_1': None
        },
        'Reply': {
            'ReplyCode': 'OK',
            'Error': [],
            'Timestamp': datetime.datetime(2023, 6, 5, 0, 56, 39, 657000, tzinfo=<FixedOffset '-05:00'>),
            'ID': [],
            '_value_1': None
        },
        'Payload': {
            '_value_1': [
                {
                    'tradingDate': datetime.date(2023, 7, 1),
                    'status': None,
                    'mode': None,
                    'submitTime': datetime.datetime(2023, 6, 13, 22, 7, 19, 36000, tzinfo=<FixedOffset '-05:00'>),
                    'COP': [],
                    'ThreePartOffer': [],
                    'OutputSchedule': [],
                    'IncDecOffer': [],
                    'CRR': [],
                    'ASOffer': [],
                    'EnergyBid': [],
                    'EnergyOnlyOffer': [],
                    'PTPObligation': [],
                    'SelfArrangedAS': [],
                    'EnergyTrade': [],
                    'CapacityTrade': [],
                    'ASTrade': [],
                    'DCTieSchedule': [],
                    'SelfSchedule': [
                        {
                            'startTime': None,
                            'endTime': None,
                            'mRID': 'QELEC3.20230701.SS.some_source.some_sink',
                            'externalId': None,
                            'marketType': None,
                            'status': 'SUBMITTED',
                            'error': [],
                            'source': None,
                            'sink': None,
                            'EnergySchedule': None
                        }
                    ],
                    'AVP': None,
                    'RTMEnergyBid': None,
                    'EFC': None
                }
            ],
            'Document': None,
            'Compressed': None,
            'format': None
        }
    },
    'success': True}    

===============
Version History
===============
======= ========== ======= =============
Version Date       Who     Release Notes
======= ========== ======= =============
0.0.0   2023-05-31 JB      Pre-Release Beta
0.0.1b  2023-06-16 JB      option to consume environment variables when instantiating ErcotClient
0.0.2b  2023-11-06 JB      Ariel added all 15 calls
0.1.0   2023-11-09 JB      First Version Released as erqse
======= ========== ======= =============
