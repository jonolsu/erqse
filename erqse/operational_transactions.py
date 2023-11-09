from zeep import Client, Transport, wsse, Settings, plugins, xsd
import requests
import uuid
from datetime import datetime, timezone, timedelta
import logging
import logging.config
from .credentials import get_credentials


ERCOT_CREDENTIALS = get_credentials("ERCOT_CREDENTIALS")


def resource_parameters_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def current_operating_plans_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def as_offer_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def three_part_offer_supply_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def output_schedule_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def self_schedule_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def as_self_arrangement_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def ptp_obligation_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def ptp_obligation_query_and_update():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def ptp_obligation_cancel():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def capacity_trade_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def energy_trade_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def as_trade_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def dam_energy_only_offer_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def dam_energy_bid_submit():
    return {"success": "False", "Notes": "Not yet implemented", "response": None}


def poc():
    wsdl_url = "wsdl/Nodal.wsdl"
    # ELECTRANET QSE I LLC (SQ2) https://www.ercot.com/files/docs/2021/11/23/Market_Participant_List.xls
    participantId = ERCOT_CREDENTIALS["PARTICIPANT_ID"]
    userId = ERCOT_CREDENTIALS["USER_ID"]
    endpoint_address = ERCOT_CREDENTIALS["ENDPOINT_ADDRESS"]

    logging.config.dictConfig(
        {
            "version": 1,
            "formatters": {
                "verbose": {"format": "%(name)s:%(levelname)s %(message)s"},
            },
            "handlers": {
                "console": {
                    "level": "WARNING",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "verbose",
                },
            },
            "loggers": {
                "zeep.transports": {
                    # 'DEBUG' is redundant since zeep.plugins.HistoryPlugin
                    "level": "WARNING",
                    "handlers": ["console"],
                },
                "urllib3": {"level": "DEBUG", "handlers": ["console"]},
                "zeep.cache": {"level": "WARNING", "handlers": ["console"]},
                "main": {"level": "DEBUG", "handlers": ["console"]},
            },
        }
    )
    logger = logging.getLogger("main")

    # Work-around: Zeep doesn't add timestamp nodes to signature
    # https://github.com/mvantellingen/python-zeep/issues/996

    class BinarySignatureTimestamp(wsse.signature.BinarySignature):
        def apply(self, envelope, headers):
            security = wsse.utils.get_security_header(envelope)

            created = datetime.now(timezone.utc).replace(microsecond=0)
            expired = created + timedelta(seconds=60)

            timestamp = wsse.utils.WSU("Timestamp")
            timestamp.append(wsse.utils.WSU("Created", created.isoformat()))
            timestamp.append(wsse.utils.WSU("Expires", expired.isoformat()))
            # timestamp.append(wsse.utils.WSU('Created', created.replace(microsecond=0).isoformat()+'Z'))
            # timestamp.append(wsse.utils.WSU('Expires', expired.replace(microsecond=0).isoformat()+'Z'))
            security.append(timestamp)

            super().apply(envelope, headers)
            return envelope, headers

        # Override response verification and skip response verification for now...
        # Zeep does not supprt Signature verification with different certificate...
        # Ref. https://github.com/mvantellingen/python-zeep/pull/822/  "Add support for different signing and verification certificates #822"
        def verify(self, envelope):
            return envelope

    # Log sent/received data
    zeep_history = plugins.HistoryPlugin()

    session = requests.Session()
    session.cert = ("cert.pem", "privkey.pem")
    client = Client(
        wsdl_url,
        transport=Transport(session=session, timeout=5, operation_timeout=5),
        wsse=BinarySignatureTimestamp(certfile="cert.pem", key_file="privkey.pem"),
        settings=Settings(forbid_entities=False),  # type: ignore #
        plugins=[zeep_history],
    )

    # load all extra .xsd's
    # if not wsdl_url.startswith('https://') and not wsdl_url.startswith('http://'):
    #     wsdl_dir = os.path.split(wsdl_url)[0]
    #     for filename in os.listdir(wsdl_dir):
    #         if filename.lower().endswith('.xsd'):
    #             print(f"loading {filename}")
    #             client.wsdl.types.add_document_by_url(os.path.join(wsdl_dir, filename))
    client.wsdl.types.add_document_by_url("wsdl/ErcotTransactions.xsd")

    service = client.create_service(
        address=endpoint_address,
        binding_name="{http://www.ercot.com/wsdl/2007-06/nodal/ewsConcrete}HttpEndPointBinding",
    )

    # § 2.1.1: Message Header Structure

    # § 7.2.2: System Status
    system_status_reqdata = {
        "Header": {
            "Verb": "get",
            "Noun": "SystemStatus",
            "Source": participantId,
            "UserID": userId,
            "ReplayDetection": {"Nonce": str(uuid.uuid4()), "Created": datetime.now().astimezone().isoformat()},
        }
    }

    # § 3.5.1: Offer and Bid Set Submission
    bidset_element = client.get_element("{http://www.ercot.com/schema/2007-06/nodal/ews}BidSet")
    create_bidset_reqdata = {
        "Header": {
            "Verb": "create",
            "Noun": "BidSet",
            "Source": participantId,
            "UserID": userId,
            "ReplayDetection": {"Nonce": str(uuid.uuid4()), "Created": datetime.now().astimezone().isoformat()},
        },
        # PayloadType contains xsd:any
        "Payload": {
            "_value_1": [
                xsd.AnyObject(
                    bidset_element,
                    bidset_element(
                        tradingDate=datetime.now(),
                        SelfSchedule=[
                            {
                                "startTime": datetime.fromisoformat("2023-06-01T12:34:56T-05:00"),
                                "endTime": datetime.fromisoformat("2023-06-02T12:34:56T-05:00"),
                                "source": "some_source",
                                "sink": "some_sink",
                            }
                        ],
                    ),
                )
            ]
        },
    }

    # Invoke the Operation
    try:
        response = service.MarketTransactions(**create_bidset_reqdata)
        return_dict = {"success": True, "Notes": "Proof of Concept to be removed later"}
        return_dict["response"] = response
        if zeep_history.last_sent:
            return_dict["sent_evelope"] = zeep_history.last_sent["envelope"]
        if zeep_history.last_received:
            return_dict["recv_envelope"] = zeep_history.last_received["envelope"]
        return return_dict
    except Exception as e:
        return {"success": False, "Notes": e}
