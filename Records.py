#!/usr/bin/python3
# -*- coding: utf-8 -*-
import re
import phonenumbers
import requests
from html import unescape
from json import loads
from phonenumbers import carrier
from phonenumbers import geocoder

from classes.types.OpseAddress import OpseAddress
from classes.types.OpsePhoneNumber import OpsePhoneNumber
from classes.Profile import Profile
from tools.Tool import Tool

from utils.config.Config import Config
from utils.DataTypeInput import DataTypeInput
from utils.DataTypeOutput import DataTypeOutput
from utils.utils import print_debug
from utils.utils import print_error


class RecordsTool(Tool):
    """
    Class which describe a RecordsTool
    """
    deprecated = False

    def __init__(self):
        """The constructor of a RecordsTool"""
        super().__init__()

    @staticmethod
    def get_config() -> dict[str]:
        """Function which return tool configuration as a dictionnary."""
        return {
            'active': True,
        }

    @staticmethod
    def get_lst_input_data_types() -> dict[str, bool]:
        """
        Function which return the list of data types which can be use to run this Tool.
        It's will help to make decision to run Tool depending on current data.
        """
        return {
            DataTypeInput.FIRSTNAME: True,
            DataTypeInput.LASTNAME: True,
            DataTypeInput.ADRESSE: False,
        }

    @staticmethod
    def get_lst_output_data_types() -> list[str]:
        """
        Function which return the list of data types which can be receive by using this Tool.
        It's will help to make decision to complete profile to get more information.
        """
        return [
            DataTypeOutput.ADDRESS,
            DataTypeOutput.PHONE_NUMBER
        ]

    def execute(self):

        firstname = str(self.get_default_profile().get_firstname())
        lastname = str(self.get_default_profile().get_lastname())

        if len(self.get_default_profile().get_lst_addresses()) > 0:
            addresses = self.get_default_profile().get_lst_addresses()
            for address in addresses:
                records_results = self.get_records_fr_118000(firstname, lastname, address.get_city())
        else:
            records_results = self.get_records_fr_118000(firstname, lastname)

        count_results = len(records_results)
        if count_results > 0:
            print_debug("Found " + str(count_results) + " results in public phone records.")
            for result in records_results:
                profile: Profile = self.get_default_profile().clone()
                profile.set_lst_phone_numbers([result['phone_number']])
                profile.set_lst_addresses([result['address']])
                self.append_profile(profile)
        else:
            print_debug("No result found in public phone records.")

    def search_fr_carrier(self, number: str) -> str:
        """
        Function which return the owner compagnie of a phone number
        """

        url = "https://www.arcep.fr/demarches-et-services/professionnels/base-numerotation.html?tx_arcepbasetechnique_basetechnique%5Bsearch%5D%5Bnumeros%5D={}".format(
            number)

        # Try to get record page matching firstname, lastname and city if available
        try:
            r = requests.post(url=url)
            page = r.content.decode('utf-8')
            print_debug("Record request ended with a " + str(r.status_code) + " status code.")
        except Exception as e:
            print_error("[RecordsTool:list_accounts] Request failed: " + str(e), True)
            return None

        carrier = ""
        carriers = re.split('a été attribué à <span class="red">(.*)</span>', page)
        if len(carriers) > 0:
            carrier = carriers[0]

        return carrier

    def get_records_fr_118000(self, firstname: str, lastname: str, location_label: str = "") -> list:
        """
        Function to list addresses of person matching firstname and lastname in public records 118000.fr
        """

        f1 = firstname + " " + lastname
        f2 = lastname + " " + firstname

        EXPECTED_COUNT_RESULTS = 25
        count_results = 25
        num_page = 1
        results = []

        while count_results == EXPECTED_COUNT_RESULTS:
            url = "https://www.118000.fr/search?label={}&who={}+{}&page={}".format(location_label, firstname, lastname,
                                                                                   num_page)

            # Try to get record page matching firstname, lastname and city if available
            try:
                r = requests.post(url=url)
                page = r.content.decode('utf-8')
                print_debug("Record request ended with a " + str(r.status_code) + " status code.")

                if r.status_code != 200:
                    num_page += 1
                    r = requests.post(url=url)
                    page = r.content.decode('utf-8')
                    if r.status_code != 200:
                        break

            except Exception as e:
                print_error("[RecordsTool:list_accounts] Request n°" + str(num_page) + " failed: " + str(e), True)
                break

            cards = re.split('<section class="card ', page)
            cards.pop(0)

            # Search in the result page the HTML anchor with name, address and phone number
            for card in cards:
                # Parse the obtained HTML object for the name
                re_fullname: list[str] = re.findall("class=lnk>([a-zA-ZÀ-ÿ0-9_ é , ]+)</a></h2>", card)
                if len(re_fullname) > 0:
                    fullname: str = re_fullname[0].title()
                    if Config.is_strict():
                        if f1.lower() != fullname.lower() and f2.lower() != fullname.lower():
                            continue
                else:
                    continue

                # Get data as a dict
                re_data = re.findall("<button type=button data-info=\"({[^<>]*})\"", card)
                if len(re_data) > 0:
                    data_json: dict = loads(unescape(re_data[0]))
                else:
                    continue

                # Parse the obtained HTML object for the address
                # re_address = re.findall("<div class=\"h4 address mtreset\">([a-zA-ZÀ-ÿ0-9_ é , </>]*)</div>", card)
                address: str = data_json.get("address")
                if address is not None:
                    # Get street number and street name
                    number = None
                    street = None
                    numbers = list(map(int, re.findall(r'\d+', address)))
                    if len(numbers) == 1:
                        number = numbers[0]
                        street = address.replace(str(number), '').strip()

                # Build Address object
                address = OpseAddress(
                    number=number,
                    street=street,
                    state_code=data_json.get("cp"),
                    city=data_json.get("city"),
                    country="France",
                    data_source="https://www.118000.fr",
                )

                # Parse the obtained HTML object for the phone number
                phone_number: str = data_json.get("tel") or data_json.get("mainLine") or None
                if phone_number is not None:
                    try:
                        tmp_phone_number = phonenumbers.parse(phone_number, "FR")
                        if phonenumbers.is_valid_number(tmp_phone_number):
                            country = geocoder.country_name_for_number(tmp_phone_number, "fr")
                            location = geocoder.description_for_number(tmp_phone_number, "fr")
                            operator = carrier.name_for_number(tmp_phone_number, "fr")
                            phone_number = OpsePhoneNumber(
                                number=str(tmp_phone_number.national_number),
                                country=country if country != "" else None,
                                country_code=str(tmp_phone_number.country_code),
                                location=location if location != "" else None,
                                carrier=operator if operator != "" else None,
                                data_source="https://www.118000.fr",
                            )
                    except Exception as e:
                        print_error("Phone number parsing failed: " + str(e))

                results.append({
                    'fullname': fullname,
                    'address': address,
                    'phone_number': phone_number or OpsePhoneNumber(None, None, None)
                })

            count_results = len(cards)
            num_page += 1

        return results

    # def get_records_fr_118712(self, firstname: str, lastname: str, location_label: str = "", subscriber_type: str = "person" or "business") -> list:
    #     """
    #     Function to list addresses of person matching firstname and lastname in public records 118712.fr
    #     """

    #     f1 = firstname + " " + lastname
    #     f2 = lastname + " " + firstname

    #     EXPECTED_COUNT_RESULTS = 25
    #     count_results = 25
    #     num_page = 1
    #     results = []

    #     while 

    #     url = "https://annuaire.118712.fr/index.php/json?s={}&subscriberType={}&jumpPage={}&lang=fr".format(firstname + '+' + lastname + '+' + location_label, subscriber_type, num_page)

    #     # Try to get record page matching firstname, lastname and city if available
    #     try:
    #         r = requests.post(url=url)
    #         res_json: dict = r.json()
    #         print_debug("Record request ended with a " + str(r.status_code) + " status code.")
    #     except Exception as e:
    #         print_error("[RecordsTool:list_accounts] Request failed: " + str(e), True)
    #         return None

    #     return []

    # def get_records_fr_baccalaureate(self, firstname: str, lastname: str, education_authority: str = ""):
    #     """
    #     Function to list person who match firstname and lastname and have their french diploma
    #     """

    #     f1 = firstname + " " + lastname
    #     f2 = lastname + " " + firstname

    #     EXPECTED_COUNT_RESULTS = 25
    #     count_results = 25
    #     num_page = 1
    #     results = []

    #     while 

    #     url = "https://annuaire.118712.fr/index.php/json?s={}&subscriberType={}&jumpPage={}&lang=fr".format(firstname + '+' + lastname + '+' + location_label, subscriber_type, num_page)

    #     # Try to get record page matching firstname, lastname and city if available
    #     try:
    #         r = requests.post(url=url)
    #         res_json: dict = r.json()
    #         print_debug("Record request ended with a " + str(r.status_code) + " status code.")
    #     except Exception as e:
    #         print_error("[RecordsTool:list_accounts] Request failed: " + str(e), True)
    #         return None

    #     return []
