from zeep import Client, Transport, wsse, plugins, Settings, xsd, exceptions as zeep_exceptions
import requests
import sqlite3
import uuid
from datetime import datetime, date, timezone, timedelta
import zoneinfo
from lxml import etree
import logging
import logging.config
import os
import typing
from dataclasses import dataclass
from typing import Optional, Any, TypedDict
from .credentials import get_credentials

from pprint import pprint

from packaging import version

if version.parse(etree.__version__) > version.parse("4.6.5"):
    raise Exception(
        f"You have lxml.etree=={etree.__version__}, which may cause problems "
        "(see https://bugs.launchpad.net/lxml/+bug/1960668/)\n"
        "If so, try lxml==4.6.5"
    )


# TODO Can we use these instead of dicts, for clarity at invocation?
class TmPoint(TypedDict):
    time: str | datetime
    ending: str | datetime
    value1: Any  # = None
    value2: Any  # = None
    value3: Any  # = None

    # def __post_init__(self):
    #     if isinstance(self.time, str):
    #         self.time = datetime.fromisoformat(self.time)
    #     if isinstance(self.ending, str):
    #         self.ending = datetime.fromisoformat(self.ending)

    # def __getitem__(self, key):
    #     return super().__getattribute__(key)


class BinarySignatureTimestamp(wsse.signature.BinarySignature):
    """Work-around: Zeep doesn't add timestamp nodes to signature
    See https://github.com/mvantellingen/python-zeep/issues/996"""

    def __init__(self, time_offset=None, *args, **kwargs):
        self.time_offset = time_offset or timedelta(0)
        super().__init__(*args, **kwargs)

    def apply(self, envelope, headers):
        security = wsse.utils.get_security_header(envelope)

        created = (datetime.now(timezone.utc) + self.time_offset).replace(microsecond=0)
        expired = created + timedelta(seconds=60)  # TODO KLUDGE

        timestamp = wsse.utils.WSU("Timestamp")
        timestamp.append(wsse.utils.WSU("Created", created.isoformat()))
        timestamp.append(wsse.utils.WSU("Expires", expired.isoformat()))
        security.append(timestamp)

        super().apply(envelope, headers)
        return envelope, headers

    def verify(self, envelope):
        """Override response verification and skip response verification for now.
        Zeep does not supprt Signature verification with different certificate.
        See https://github.com/mvantellingen/python-zeep/pull/822/"""
        return envelope


@dataclass
class ErcotClient:
    endpoint_url: str = None
    cert_filename: str = None
    key_filename: str = None
    participantId: str = None
    userId: str = None
    wsdl_timeout: int = None
    operation_timeout: int = None
    trace: bool = False
    time_offset: timedelta = timedelta(0)

    class SqliteLoggerPlugin(plugins.Plugin):
        def __init__(self, db_filename="soap.sqlite", tablename="soap_log", timezone="US/Central"):
            self.dbconn = sqlite3.connect(db_filename)
            self.tablename = tablename
            self.timezone = timezone
            cursor = self.dbconn.cursor()

            ## Check the destination table
            cursor.execute("pragma main.table_info('{}')".format(tablename))
            cols = cursor.fetchall()
            if not cols:
                print("'{}' does not exist at the destination - creating".format(tablename))
                cursor.execute(
                    f"create table {tablename} "
                    "(time timestamp, operation text, url text, "
                    "req_resp text, headers text, data text)"
                )

        def egress(self, envelope, http_headers, operation, binding_options):
            cursor = self.dbconn.cursor()
            cursor.execute(
                f"INSERT INTO {self.tablename}(time, operation, url, req_resp, headers, data) "
                "VALUES(?, ?, ?, 'request', ?, ?)",
                (
                    datetime.now().astimezone(zoneinfo.ZoneInfo(self.timezone)).isoformat(),
                    operation.name,
                    binding_options["address"],
                    "\n".join(f"{k}: {v}" for k, v in http_headers.items()),
                    etree.tostring(
                        envelope.xpath("//soap:Body", namespaces={"soap": "http://schemas.xmlsoap.org/soap/envelope/"})[
                            0
                        ],
                        pretty_print=True,
                    ),
                ),
            )
            self.dbconn.commit()

        def ingress(self, envelope, http_headers, operation):
            cursor = self.dbconn.cursor()
            cursor.execute(
                f"INSERT INTO {self.tablename}(time, operation, req_resp, headers, data) "
                "VALUES(?, ?, 'response', ?, ?)",
                (
                    datetime.now().astimezone(zoneinfo.ZoneInfo(self.timezone)).isoformat(),
                    operation.name,
                    "\n".join(f"{k}: {v}" for k, v in http_headers.items()),
                    etree.tostring(
                        envelope.xpath("//soap:Body", namespaces={"soap": "http://schemas.xmlsoap.org/soap/envelope/"})[
                            0
                        ],
                        pretty_print=True,
                    ),
                ),
            )
            self.dbconn.commit()

    def __post_init__(self):
        # TODO configure logging
        ercot_credentials = get_credentials("ERCOT_CREDENTIALS")
        if self.userId is None:
            self.userId = ercot_credentials["USER_ID"]
        if self.participantId is None:
            self.participantId = ercot_credentials["PARTICIPANT_ID"]
        if self.endpoint_url is None:
            self.endpoint_url = ercot_credentials["ENDPOINT_URL"]
        if self.cert_filename is None:
            self.cert_filename = ercot_credentials["PATH_TO_CERT_FILE"]
        if self.key_filename is None:
            self.key_filename = ercot_credentials["PATH_TO_KEY_FILE"]
        self.session = requests.Session()
        self.session.cert = (self.cert_filename, self.key_filename)
        self.zeep_history = plugins.HistoryPlugin()
        _here = os.path.abspath(os.path.dirname(__file__))
        self.wsdl_file = os.path.join(_here, "wsdl", "Nodal.wsdl")
        self.client = Client(
            self.wsdl_file,
            transport=Transport(
                session=self.session, timeout=self.wsdl_timeout, operation_timeout=self.operation_timeout
            ),
            wsse=BinarySignatureTimestamp(
                certfile=self.cert_filename, key_file=self.key_filename, time_offset=self.time_offset
            ),
            settings=Settings(forbid_entities=False),  # type: ignore #
            # plugins=[self.zeep_history]
            plugins=[self.zeep_history],
        )
        self.client.plugins.append(self.SqliteLoggerPlugin())

        document_filename = "ErcotTransactions.xsd"
        document_path_and_filename = os.path.join(_here, "wsdl", document_filename)
        # load extra .xsd's
        # self.client.wsdl.types.add_document_by_url(
        #     os.path.join(os.path.split(self.wsdl_url)[0], "ErcotTransactions.xsd"))  # TODO canonical path manip
        self.client.wsdl.types.add_document_by_url(document_path_and_filename)

        self.service = self.client.create_service(
            address=self.endpoint_url,
            binding_name="{http://www.ercot.com/wsdl/2007-06/nodal/ewsConcrete}HttpEndPointBinding",
        )

    def _make_header(self, noun, verb):
        return {
            "Verb": verb,
            "Noun": noun,
            "Source": self.participantId,
            "UserID": self.userId,
            "ReplayDetection": {
                "Nonce": str(uuid.uuid4()),
                "Created": (datetime.now() + self.time_offset).astimezone().isoformat(),
            },
        }

    def _market_transactions(self, req_data):  # TODO use get_service
        raise NotImplementedError("DISABLED")
        try:
            response = self.service.MarketTransactions(**req_data)
            ret_val = {"success": True, "response": response}
        except Exception as e:
            ret_val = {"success": False, "Exception": e}
        if self.trace or "Exception" in ret_val:
            if self.zeep_history.last_sent:
                ret_val["sent_envelope"] = etree.tostring(
                    self.zeep_history.last_sent["envelope"], pretty_print=True
                ).decode()
            if self.zeep_history.last_received:
                ret_val["recv_envelope"] = etree.tostring(
                    self.zeep_history.last_received["envelope"], pretty_print=True
                ).decode()
        return ret_val

    def _market_info(self, req_data):  # TODO use get_service
        raise NotImplementedError("DISABLED")
        try:
            response = self.service.MarketInfo(**req_data)
            ret_val = {"success": True, "response": response}
        except Exception as e:
            ret_val = {"success": False, "Exception": e}
        if self.trace or "Exception" in ret_val:
            if self.zeep_history.last_sent:
                ret_val["sent_evelope"] = etree.tostring(
                    self.zeep_history.last_sent["envelope"], pretty_print=True
                ).decode()
            if self.zeep_history.last_received:
                ret_val["recv_envelope"] = etree.tostring(
                    self.zeep_history.last_received["envelope"], pretty_print=True
                ).decode()
        return ret_val

    def _consume(self, service_name, req_data):
        try:
            response = self.service[service_name](**req_data)

            # replace unparsed XML elements
            # TODO search is kludgy/specific
            if (
                "Payload" in response
                and hasattr(response["Payload"], "__getitem__")
                and "_value_1" in response["Payload"]
                and hasattr(response["Payload"]["_value_1"], "__iter__")
            ):
                for idx, item in enumerate(response["Payload"]["_value_1"]):
                    if isinstance(item, etree._Element):
                        try:
                            _elem = self.client.get_element(item.tag)
                            # print(f"Replacing [\"Payload\"][\"_value_1\"][{idx}]: {item.tag}") # e.g. {http://www.ercot.com/schema/2007-06/nodal/ews}BidSet
                            response["Payload"]["_value_1"][idx] = _elem.parse(item, None)
                        except zeep_exceptions.LookupError as e:
                            pass
                            # print(f"Could not find an Element to parse "
                            #       f"[\"Payload\"][\"_value_1\"][{idx}]: = " +
                            #       etree.tostring(item).decode())

            ret_val = {}
            try:
                # the operation may still have failed
                ret_val["success"] = response.Reply.ReplyCode == "OK"
            except AttributeError:
                ret_val["success"] = False
            ret_val["response"] = response
        except Exception as e:
            import traceback

            ret_val = {"success": False, "Exception": str(e), "FullException": traceback.format_exc()}
        if self.trace or "Exception" in ret_val:
            if self.zeep_history.last_sent:
                ret_val["sent_evelope"] = etree.tostring(
                    self.zeep_history.last_sent["envelope"], pretty_print=True
                ).decode()
            if self.zeep_history.last_received:
                ret_val["recv_envelope"] = etree.tostring(
                    self.zeep_history.last_received["envelope"], pretty_print=True
                ).decode()
        return ret_val

    def system_status(self):
        """Implements § 7.2.2: System Status"""

        class ReplayDetection(TypedDict):
            Nonce: str
            Created: datetime | str

        req_data = {"Header": self._make_header("SystemStatus", "get")}
        return self._consume("MarketInfo", req_data)

    def bidset_submit(self, data: dict, _update: bool = False):
        # Get the xml element from the schema
        if not hasattr(self, "_bidset_element"):
            self._bidset_element = self.client.get_element("{http://www.ercot.com/schema/2007-06/nodal/ews}BidSet")

        req_data = {
            "Header": self._make_header("BidSet", "change" if _update else "create"),
            # PayloadType contains xsd:any
            "Payload": {
                "_value_1": [
                    xsd.AnyObject(
                        self._bidset_element,
                        self._bidset_element(**data),
                    )
                ]
            },
        }
        # TODO reply["response"]["Payload"]["_value_1"][0] is lxml.etree._Element; postprocess?
        return self._consume("MarketTransactions", req_data)

    def bidset_update(self, data: dict):
        return self.bidset_submit(data, _update=True)

    def bidset_get(self, mRID: list | str):
        req_data = {"Header": self._make_header("BidSet", "get"), "Request": {"ID": mRID}}
        return self._consume("MarketInfo", req_data)

    def bidset_cancel(self, mRID: list | str):
        req_data = {"Header": self._make_header("BidSet", "cancel"), "Request": {"ID": mRID}}
        return self._consume("MarketInfo", req_data)

    def selfschedule_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        source: str,
        sink: str,
        energySchedule: list[dict],
    ):  # {time: datetime, ending: datetime, value1: float, multiHourBlock: bool = False}
        if isinstance(startTime, str):
            startTime = datetime.fromisoformat(startTime)
        if isinstance(endTime, str):
            endTime = datetime.fromisoformat(endTime)
        req_data = {
            "tradingDate": tradingDate,
            "SelfSchedule": {
                "startTime": startTime,
                "endTime": endTime,
                "source": source,
                "sink": sink,
                "EnergySchedule": {"TmPoint": energySchedule},
            },
        }
        return self.bidset_submit(req_data)

    def ptpobligation_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        source: str,
        sink: str,
        bidId: str,
        maximumPrice: list[dict],
        capacitySchedule: list[dict],  # {time: datetime, ending: datetime, value1: float, multiHourBlock: bool = False}
        marketType: str = None,
        externalId: str = None,
        _update=False,
    ):
        """Submits a BidSet with _one_ PTPObligation § 3.3.14"""

        # conversions serve as validation
        if isinstance(startTime, str):
            startTime = datetime.fromisoformat(startTime)
        if isinstance(endTime, str):
            endTime = datetime.fromisoformat(endTime)
        req_data = {
            "tradingDate": tradingDate,
            "PTPObligation": [
                {
                    "startTime": startTime,  # TODO meaning?
                    "endTime": endTime,  # TODO meaning?
                    "source": source,
                    "sink": sink,
                    "marketType": marketType,  # TODO meaning?
                    "bidId": bidId,  # TODO user supplied?
                    "MaximumPrice": maximumPrice,
                    "CapacitySchedule": {"TmPoint": capacitySchedule},
                    "externalId": externalId,
                }
            ],
        }
        return self.bidset_submit(req_data, _update)

    def ptpobligation_update(self, **kwargs):
        return self.ptpobligation_submit(**kwargs, _update=True)

    def ptpobligation_get(self, mRID: list | str):
        return self.bidset_get(mRID)

    def ptpobligation_cancel(self, mRID: list | str):
        return self.bidset_cancel(mRID)

    def capacitytrade_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        buyer: str,
        seller: str,
        capacitySchedule: list[dict],
        marketType: str = None,
        otherPartySubmitted: bool = None,
        tradeId: str = None,
        externalId: str = None,
    ):
        if isinstance(startTime, str):
            startTime = datetime.fromisoformat(startTime)
        if isinstance(endTime, str):
            endTime = datetime.fromisoformat(endTime)
        req_data = {
            "tradingDate": tradingDate,
            "CapacityTrade": {
                "startTime": startTime,
                "endTime": endTime,
                "marketType": marketType,
                "buyer": buyer,
                "seller": seller,
                "tradeID": tradeId,
                "externalId": externalId,
                "otherPartySubmitted": otherPartySubmitted,
                "CapacitySchedule": {"TmPoint": capacitySchedule},
            },
        }
        return self.bidset_submit(req_data)

    def energytrade_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        buyer: str,
        seller: str,
        settlementPoint: str,
        energySchedule: list[dict],
        marketType: str = None,
        otherPartySubmitted: bool = None,
        tradeId: str = None,
        externalId: str = None,
    ):
        if isinstance(startTime, str):
            startTime = datetime.fromisoformat(startTime)
        if isinstance(endTime, str):
            endTime = datetime.fromisoformat(endTime)
        req_data = {
            "tradingDate": tradingDate,
            "EnergyTrade": {
                "startTime": startTime,
                "endTime": endTime,
                "marketType": marketType,
                "buyer": buyer,
                "seller": seller,
                "sp": settlementPoint,
                "tradeID": tradeId,
                "externalId": externalId,
                "otherPartySubmitted": otherPartySubmitted,
                "EnergySchedule": {"TmPoint": energySchedule},
            },
        }
        return self.bidset_submit(req_data)

    def astrade_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        buyer: str,
        seller: str,
        asType: str,
        # "Non-Spin","NSPNM","Reg-Down","Reg-Up",
        # "RRSUF","RRSPF","RRSFF"(,"ECRSS","ECRSM")?
        asSchedule: list[dict] | dict,
        marketType: str = None,
        otherPartySubmitted: bool = None,
        tradeId: str = None,
        externalId: str = None,
    ):
        if isinstance(startTime, str):
            startTime = datetime.fromisoformat(startTime)
        if isinstance(endTime, str):
            endTime = datetime.fromisoformat(endTime)
        req_data = {
            "tradingDate": tradingDate,
            "ASTrade": {
                "startTime": startTime,
                "endTime": endTime,
                "marketType": marketType,
                "buyer": buyer,
                "seller": seller,
                "tradeID": tradeId,
                "externalId": externalId,
                "otherPartySubmitted": otherPartySubmitted,
                "asType": asType,
                "ASSchedule": {"TmPoint": asSchedule},
            },
        }
        return self.bidset_submit(req_data)

    def selfarranged_as_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        asType: str,
        # "Reg-Up","Reg-Down","Non-Spin","RRS","RRSUF","RRSPF","RRSFF"(,"ECRS")?
        capacitySchedule: list[dict] | dict,
        rrsValues: list[dict] | dict = None,
        externalId: str = None,
    ):
        if isinstance(startTime, str):
            startTime = datetime.fromisoformat(startTime)
        if isinstance(endTime, str):
            endTime = datetime.fromisoformat(endTime)
        req_data = {
            "tradingDate": tradingDate,
            "SelfArrangedAS": {
                "startTime": startTime,
                "endTime": endTime,
                "asType": asType,
                "externalId": externalId,
                "CapacitySchedule": {"TmPoint": capacitySchedule, "rrs_values": rrsValues},
            },
        }
        return self.bidset_submit(req_data)

    def energybid_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        expirationTime: datetime | str,
        settlementPoint: str,
        bidId: str,
        curveData: list[dict] | dict,
        curveStyle: str,  # FIXED/VARIABLE/CURVE (WSDL says minOccurs=0)
        marketType: str = None,
        multiHourBlock: bool = None,
        externalId: str = None,
    ):
        if isinstance(startTime, str):
            startTime = datetime.fromisoformat(startTime)
        if isinstance(endTime, str):
            endTime = datetime.fromisoformat(endTime)
        if isinstance(tradingDate, str):
            tradingDate = datetime.fromisoformat(tradingDate)
        req_data = {
            "tradingDate": tradingDate,
            "EnergyBid": {
                "startTime": startTime,  # | |--Bid
                "endTime": endTime,  # | |
                "externalId": externalId,  # | |
                "marketType": marketType,  # | |
                "expirationTime": expirationTime,  # |--EnergyBid
                "sp": settlementPoint,  # |
                "bidID": bidId,  # |
                "PriceCurve": {  # |
                    "startTime": startTime,  # | |--PriceCurve
                    "endTime": endTime,  # | |
                    "curveStyle": curveStyle,  # | |
                    "CurveData": curveData,  # | |
                    "multiHourBlock": multiHourBlock,  # | |
                },
            },
        }
        return self.bidset_submit(req_data)

    def energyonlyoffer_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        expirationTime: datetime | str,
        settlementPoint: str,
        bidId: str,
        curveStyle: str,
        curveData: list[dict] | dict,
        multiHourBlock: bool = False,
        marketType: str = None,
        externalId: str = None,
    ):
        if isinstance(startTime, str):
            startTime = datetime.fromisoformat(startTime)
        if isinstance(endTime, str):
            endTime = datetime.fromisoformat(endTime)
        if isinstance(tradingDate, str):
            tradingDate = datetime.fromisoformat(tradingDate)
        if isinstance(expirationTime, str):
            expirationTime = datetime.fromisoformat(expirationTime)
        req_data = {
            "tradingDate": tradingDate,
            "EnergyOnlyOffer": {
                "startTime": startTime,
                "endTime": endTime,
                "externalId": externalId,
                "sp": settlementPoint,
                "marketType": marketType,
                "bidID": bidId,
                "expirationTime": expirationTime,
                "EnergyOfferCurve": {
                    "startTime": startTime,
                    "endTime": endTime,
                    "curveStyle": curveStyle,
                    "CurveData": curveData,
                    "multiHourBlock": multiHourBlock,
                },
            },
        }
        return self.bidset_submit(req_data)

    # Resource-specific bids

    def currentoperatingplan_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        resourceStatus: dict | list[dict],
        limits: dict | list[dict],
        asCapacity: dict | list[dict],
        resource: str,
        combinedCycle: str = None,
        externalId: str = None,
    ):
        """### Current Operating Plan (COP) § 3.3.9"""
        if isinstance(startTime, str):
            startTime = datetime.fromisoformat(startTime)
        if isinstance(endTime, str):
            endTime = datetime.fromisoformat(endTime)
        if isinstance(tradingDate, str):
            tradingDate = datetime.fromisoformat(tradingDate)
        req_data = {
            "tradingDate": tradingDate,
            "COP": {
                "startTime": startTime,
                "endTime": endTime,
                "externalId": externalId,
                "resource": resource,
                "combinedCycle": combinedCycle,
                "ResourceStatus": resourceStatus,
                "Limits": limits,
                "ASCapacity": asCapacity,
            },
        }
        return self.bidset_submit(req_data)

    def aso_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        expirationTime: datetime | str,
        asType: str,  # Off-Non-Spin, On-Non-Spin, REGUP-RRS-ONNS, RSSUF, RSSPF, RSSFF
        resource: str,
        asPriceCurve: dict | list[dict],
        combinedCycle: str = None,
        externalId: str = None,
    ):
        """Ancillary Service Offer (ASOffer/ASO) § 3.3.4"""
        if isinstance(startTime, str):
            startTime = datetime.fromisoformat(startTime)
        if isinstance(endTime, str):
            endTime = datetime.fromisoformat(endTime)
        if isinstance(tradingDate, str):
            tradingDate = datetime.fromisoformat(tradingDate)
        if isinstance(expirationTime, str):
            expirationTime = datetime.fromisoformat(expirationTime)
        if asType in ["Reg-Up", "REGUP-RRS-ONNS", "On-Non-Spin"]:
            asPriceCurve_type = "OnLineReserves"
        elif asType in ["Reg-Down"]:
            asPriceCurve_type = "RegDown"
        elif asType in ["Off-Non-Spin", "OFFEC"]:
            asPriceCurve_type = "OffLineNonSpin"
        else:
            raise ValueError(f"Unsupported AS type '{asType}")

        req_data = {
            "tradingDate": tradingDate,
            "ASOffer": {
                "startTime": startTime,
                "endTime": endTime,
                "expirationTime": expirationTime,
                "externalId": externalId,
                "resource": resource,
                "asType": asType,
                "combinedCycle": combinedCycle,
                "ASPriceCurve": {"startTime": startTime, "endTime": endTime, asPriceCurve_type: asPriceCurve},
            },
        }
        # pprint(req_data)
        return self.bidset_submit(req_data)

    def threepartoffer_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        expirationTime: datetime | str,
        eocFipFop: dict | list[dict],
        resource: str,
        suMeFipFop: dict | list[dict] = None,
        startupCost: dict | list[dict] = None,
        minimumEnergy: dict | list[dict] = None,
        energyOfferCurve: dict = None,
        combinedCycle: str = None,
    ):
        """Three Part Supply Offer (TPO) § 3.3.1"""
        if isinstance(startTime, str):
            startTime = datetime.fromisoformat(startTime)
        if isinstance(endTime, str):
            endTime = datetime.fromisoformat(endTime)
        if isinstance(tradingDate, str):
            tradingDate = datetime.fromisoformat(tradingDate)
        if isinstance(expirationTime, str):
            expirationTime = datetime.fromisoformat(expirationTime)
        req_data = {
            "tradingDate": tradingDate,
            "ThreePartOffer": {
                "startTime": startTime,
                "endTime": endTime,
                "expirationTime": expirationTime,
                "resource": resource,
                "EocFipFop": eocFipFop,
                "SuMeFipFop": suMeFipFop,
                "MinimumEnergy": minimumEnergy,
                "StartupCost": startupCost,
                "EnergyOfferCurve": energyOfferCurve,
                "combinedCycle": combinedCycle,
            },
        }
        return self.bidset_submit(req_data)

    def outputschedule_submit(
        self,
        tradingDate: date | datetime | str,
        startTime: datetime | str,
        endTime: datetime | str,
        resource: str,
        energySchedule: dict | list[dict],
        deleteTPOs: bool = True,
        marketType: str = None,
        externalId: str = None,
    ):
        req_data = {
            "tradingDate": tradingDate,
            "OutputSchedule": {
                "startTime": startTime,
                "endTime": endTime,
                "resource": resource,
                "deleteTPOs": deleteTPOs,
                "marketType": marketType,
                "externalId": externalId,
                "EnergySchedule": {"TmPoint": energySchedule},
            },
        }
        return self.bidset_submit(req_data)

    def resourceparameters_get(self, typeCode: str, resource: str = None):
        req_data = {
            "Header": self._make_header("ResParametersSet", "get"),
            "Request": {
                "ID": (
                    f"{self.participantId}.{typeCode}.{resource}" if resource else f"{self.participantId}.{typeCode}"
                )
            },
        }
        return self._consume("MarketInfo", req_data)

    def _resourceparameters_submit(self, data: dict):
        """Generic Resource Parameters submit wrapper"""
        # Get the xml element from the schema
        if not hasattr(self, "_resparametersset_element"):
            self._resparametersset_element = self.client.get_element(
                "{http://www.ercot.com/schema/2007-06/nodal/ews}ResParametersSet"
            )

        req_data = {
            "Header": self._make_header("ResParametersSet", "change"),
            # PayloadType contains xsd:any
            "Payload": {
                "_value_1": [
                    xsd.AnyObject(
                        self._resparametersset_element,
                        self._resparametersset_element(**data),
                    )
                ]
            },
        }
        # TODO reply["response"]["Payload"]["_value_1"][0] is lxml.etree._Element; postprocess?
        return self._consume("MarketTransactions", req_data)

    def genresourceparameters_submit(
        self,
        resource: str,
        normalRrCurve: dict | list[dict],
        emergencyRrCurve: dict | list[dict],
        minOnlineTime: float,
        minOfflineTime: float,
        maxOnlineTime: float,
        maxDailyStarts: int,
        hotStartTime: float,
        intermediateStartTime: float,
        coldStartTime: float,
        hotToIntermediateTime: float,
        intermediateToColdTime: float,
        maxWeeklyStarts: int,
        maxWeeklyEnergy: float,
        reason: str,
        externalId: str = None,
    ):
        """Generator Resource Parameters § 9.3.1"""
        req_data = {
            "GenResourceParameters": {
                # "mRID": f"{self.participantId}.GEN.{resource}", #TODO: needed?
                "resource": resource,
                "normalRrCurve": {"rrPoint": normalRrCurve},
                "emergencyRrCurve": {"rrPoint": emergencyRrCurve},
                "Details": {
                    "minOnlineTime": minOnlineTime,
                    "minOfflineTime": minOfflineTime,
                    "maxOnlineTime": maxOnlineTime,
                    "maxDailyStarts": maxDailyStarts,
                    "hotStartTime": hotStartTime,
                    "intermediateStartTime": intermediateStartTime,
                    "coldStartTime": coldStartTime,
                    "hotToIntermediateTime": hotToIntermediateTime,
                    "intermediateToColdTime": intermediateToColdTime,
                    "maxWeeklyStarts": maxWeeklyStarts,
                    "maxWeeklyEnergy": maxWeeklyEnergy,
                },
                "reason": reason,
                "externalId": externalId,
            }
        }
        return self._resourceparameters_submit(req_data)

    def conresourceparameters_submit(
        self,
        resource: str,
        normalRrCurve: dict | list[dict],
        emergencyRrCurve: dict | list[dict],
        maxDeploymentTime: float,
        maxWeeklyEnergy: int,
        reason: str,
        externalId: str = None,
    ):
        """Controllable Load Resource Parameters § 9.3.2"""
        req_data = {
            "ControllableLoadResource": {
                # "mRID": f"{self.participantId}.CON.{resource}", #TODO: needed?
                "resource": resource,
                "normalRrCurve": {"rrPoint": normalRrCurve},
                "emergencyRrCurve": {"rrPoint": emergencyRrCurve},
                "Details": {"maxDeploymentTime": maxDeploymentTime, "maxWeeklyEnergy": maxWeeklyEnergy},
                "reason": reason,
                "externalId": externalId,
            }
        }
        return self._resourceparameters_submit(req_data)

    def nonresourceparameters_submit(
        self,
        resource: str,
        minInterruptionTime: float,
        minRestorationTime: float,
        minNoticeTime: float,
        maxInterruptionTime: float,
        maxDailyDeployments: int,
        maxWeeklyDeployments: int,
        maxWeeklyEnergy: int,
        reason: str,
        externalId: str = None,
    ):
        """Non-Controllable Load Resource Parameters § 9.3.3"""
        req_data = {
            "NonControllableLoadResource": {
                # "mRID": f"{self.participantId}.NON.{resource}", #TODO: needed?
                "resource": resource,
                "Details": {
                    "minInterruptionTime": minInterruptionTime,
                    "minRestorationTime": minRestorationTime,
                    "minNoticeTime": minNoticeTime,
                    "maxInterruptionTime": maxInterruptionTime,
                    "maxDailyDeployments": maxDailyDeployments,
                    "maxWeeklyDeployments": maxWeeklyDeployments,
                    "maxWeeklyEnergy": maxWeeklyEnergy,
                },
                "reason": reason,
                "externalId": externalId,
            }
        }
        return self._resourceparameters_submit(req_data)

    def resourceparameters_submit(
        self, resource: str, highReasonabilityLimit: float, lowReasonabilityLimit: float, externalId: str = None
    ):
        """Non-Controllable Load Resource Parameters § 9.3.4"""
        req_data = {
            "ResourceParameters": {
                # "mRID": f"{self.participantId}.NON.{resource}", #TODO: needed?
                "resource": resource,
                "rrReasonabilityLimits": {
                    "highReasonabilityLimit": highReasonabilityLimit,
                    "lowReasonabilityLimit": lowReasonabilityLimit,
                },
                "externalId": externalId,
            }
        }
        return self._resourceparameters_submit(req_data)
