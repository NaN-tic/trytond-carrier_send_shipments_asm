# This file is part of the carrier_send_shipments_asm module for Tryton.
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
import logging
from trytond.pool import PoolMeta
from trytond.i18n import gettext
from trytond.exceptions import UserError
from asm.picking import *

__all__ = ['CarrierApi']


class CarrierApi(metaclass=PoolMeta):
    __name__ = 'carrier.api'

    @classmethod
    def get_carrier_app(cls):
        'Add Carrier ASM APP'
        res = super(CarrierApi, cls).get_carrier_app()
        res.append(('asm', 'ASM'))
        return res

    @classmethod
    def test_asm(cls, api):
        'Test ASM connection'
        message = 'Connection unknown result'

        with API(api.username, api.debug) as asm_api:
            message = asm_api.test_connection()
        raise UserError(gettext(
            'carrier_send_shipments_asm.msg_asm_test_connection',
            message=message))
