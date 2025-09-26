import asyncio
import hashlib
import time
import urllib
from datetime import datetime

import aiohttp

DOMAIN_BASE_URL = 'web.dessmonitor.com'

headers = {
    'Host': DOMAIN_BASE_URL,
    'Origin': DOMAIN_BASE_URL,
    'Referer': 'https://www.dessmonitor.com/',
    'DNT': '1',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
}

api_semaphore = asyncio.Semaphore(10)


async def auth_user(username: str, password_hash: str):
    async with aiohttp.ClientSession() as session:
        # print('auth_user', username)
        params = {
            'action': 'authSource',
            'usr': username,
            'source': '1',
            'company-key': 'bnrl_frRFjEz8Mkn',
        }
        qs = urllib.parse.urlencode(params, doseq=False, safe='@')
        salt = int(time.time())
        sign = hashlib.sha1(f'{salt}{password_hash}&{qs}'.encode()).hexdigest()
        payload = {
            'sign': sign,
            'salt': salt,
            **params,
        }
        url = f'https://{DOMAIN_BASE_URL}/public/?{urllib.parse.urlencode(payload, doseq=False, safe="@")}'
        response = (await (await session.get(url, headers=headers)).json())
        if response['err'] != 0:
            print(f'Error {response["err"]} while authenticating user: {response["desc"]}')
            raise Exception(
                f'ErrorAuthFailed'
            )
        data = response['dat']
        return {
            'token': data['token'],
            'secret': data['secret'],
            'expire': data['expire'],
            'uid': data['uid'],
            'usr': data['usr'],
        }


def generate_signature(salt, secret, token, params):
    qs = urllib.parse.urlencode(params, doseq=False, safe='@')
    return hashlib.sha1(f'{salt}{secret}{token}&{qs}'.encode()).hexdigest()


def generate_params_signature(token, secret, params):
    salt = int(time.time())
    return {
        'sign': generate_signature(salt, secret, token, params),
        'salt': salt,
        'token': token,
        **params,
    }


async def create_auth_api_request(token, secret, params, raise_error=True):
    async with aiohttp.ClientSession() as session:
        async with api_semaphore:
            payload = generate_params_signature(token, secret, params)
            # print(payload)
            params_path = urllib.parse.urlencode(payload, doseq=False, safe="@")
            url = f'https://{DOMAIN_BASE_URL}/public/?{params_path}'
            json = (await (await session.get(url, headers=headers)).json())
            if json['err'] == 0:
                return json['dat']
            else:
                if raise_error:
                    if json['err'] == 10:
                        raise AuthInvalidateError
                    raise Exception(
                        f'Error {json["err"]} while creating auth api request: {json["desc"]}'
                    )
                else:
                    return json


class AuthInvalidateError(Exception):
    pass


async def create_auth_api_remote_request(token, secret, params, raise_error=True):
    async with aiohttp.ClientSession() as session:
        async with api_semaphore:
            payload = generate_params_signature(token, secret, params)
            # print(payload)
            params_path = urllib.parse.urlencode(payload, doseq=False, safe="@")
            url = f'https://{DOMAIN_BASE_URL}/remote/?{params_path}'
            json = (await (await session.get(url, headers=headers)).json())
            if json['err'] == 0:
                return json['dat']
            else:
                if raise_error:
                    raise Exception(
                        f'Error {json["err"]} while creating auth api request: {json["desc"]}'
                    )
                else:
                    return json


async def get_devices(token, secret, params=None):
    if params is None:
        params = {}
    payload = {
        'action': 'webQueryDeviceEs',
        'i18n': 'en_US',
        'source': '1',
        'page': '0',
        'pagesize': '15',
        # 'status': '0',
        **params,
    }
    devices_response = await create_auth_api_request(token, secret, payload)

    return devices_response['device']


def extract_device_identity(device):
    return {
        'devaddr': device['devaddr'],
        'devcode': device['devcode'],
        'pn': device['pn'],
        'sn': device['sn'],
    }


async def get_device_energy_flow(token, secret, device_identity):
    payload = {
        'action': 'webQueryDeviceEnergyFlowEs',
        'i18n': 'en_US',
        'source': '1',
        **extract_device_identity(device_identity)
    }
    response = await create_auth_api_request(token, secret, payload)

    return response


async def get_device_last_data(token, secret, device_identity):
    payload = {
        'action': 'querySPDeviceLastData',
        'i18n': 'en_US',
        'source': '1',
        **extract_device_identity(device_identity)
    }
    response = await create_auth_api_request(token, secret, payload)

    return response


async def get_device_pars(token, secret, device_identity):
    payload = {
        'action': 'queryDeviceParsEs',
        'i18n': 'en_US',
        'source': '1',
        **extract_device_identity(device_identity)
    }
    response = await create_auth_api_request(token, secret, payload)

    return response


async def get_device_ctrl_value(token: str, secret: str, device_identity, param_id: str):
    payload = {
        'action': 'queryDeviceCtrlValue',
        'i18n': 'en_US',
        'source': '1',
        'id': param_id,
        **extract_device_identity(device_identity),
    }
    start = int(datetime.now().timestamp() * 1000)
    # print(payload)
    response = await create_auth_api_request(token, secret, payload, False)
    # print('get_device_ctrl_value time', int(datetime.now().timestamp() * 1000) - start)
    return response


async def get_device_ctrl_fields(token: str, secret: str, device_identity):
    payload = {
        'action': 'queryDeviceCtrlField',
        'i18n': 'en_US',
        'source': '1',
        **extract_device_identity(device_identity),
    }
    response = await create_auth_api_request(token, secret, payload)

    return response


async def get_device_fields(token: str, secret: str, device_identity):
    payload = {
        'action': 'queryDeviceFields',
        'i18n': 'en_US',
        'source': '1',
        **extract_device_identity(device_identity),
    }
    response = await create_auth_api_request(token, secret, payload)

    return response


async def get_device_historical_data(token: str, secret: str, device_identity):
    payload = {
        'action': 'queryDeviceDataOneDayPaging',
        'i18n': 'en_US',
        'source': '1',
        'page': '0',
        'pagesize': '15',
        'date': '2025-03-07',
        **extract_device_identity(device_identity),
    }
    response = await create_auth_api_request(token, secret, payload)

    return response


async def get_collectors(token, secret, params):
    payload = {
        'action': 'webQueryCollectorsEs',
        'source': '1',
        'devtype': '2304',
        'page': '0',
        'pagesize': '15',
        **params,
    }
    response = await create_auth_api_request(token, secret, payload)

    return response


async def set_ctrl_device_param(token: str, secret: str, device_identity, param_id: str, value: str):
    payload = {
        'action': 'ctrlDevice',
        'i18n': 'en_US',
        'source': '1',
        'id': param_id,
        'val': value,
        **extract_device_identity(device_identity),
    }
    response = await create_auth_api_request(token, secret, payload)

    return response


async def send_device_direct_command(token: str, secret: str, device_identity, cmd: str):
    payload = {
        'action': 'sendCmdToDevice',
        'source': '1',
        'cmd': cmd,
        **extract_device_identity(device_identity),
    }
    response = await create_auth_api_request(token, secret, payload)

    return response
