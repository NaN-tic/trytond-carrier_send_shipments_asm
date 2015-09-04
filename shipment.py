# This file is part of the carrier_send_shipments_asm module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from asm.picking import Picking
from asm.utils import services as asm_services
from trytond.modules.carrier_send_shipments.tools import unaccent
from base64 import decodestring
import logging
import tempfile

__all__ = ['ShipmentOut']
__metaclass__ = PoolMeta


class ShipmentOut:
    __name__ = 'stock.shipment.out'

    @classmethod
    def __setup__(cls):
        super(ShipmentOut, cls).__setup__()
        cls._error_messages.update({
            'asm_add_services': 'Select a service or default service in ASM API',
            'asm_not_country': 'Add country in shipment "%(name)s" delivery address',
            'asm_not_price': 'Shipment "%(name)s" not have price and send '
                'cashondelivery',
            'asm_error_zip': 'ASM not accept zip "%(zip)s"',
            'asm_not_send': 'Not send shipment %(name)s',
            'asm_not_send_error': 'Not send shipment %(name)s. %(error)s',
            'asm_not_label': 'Not available "%(name)s" label from ASM',
            'asm_add_oficina': 'Add a office ASM to delivery or change service',
            })

    @staticmethod
    def asm_picking_data(api, shipment, service, price=None, weight=False):
        '''
        ASM Picking Data
        :param api: obj
        :param shipment: obj
        :param service: str
        :param price: string
        :param weight: bol
        Return data
        '''
        Uom = Pool().get('product.uom')

        packages = shipment.number_packages
        if not packages or packages == 0:
            packages = 1

        remitente_address = shipment.warehouse.address or shipment.company.party.addresses[0]

        if api.reference_origin and hasattr(shipment, 'origin'):
            code = shipment.origin and shipment.origin.rec_name or shipment.code
        else:
            code = shipment.code

        notes = ''
        if shipment.carrier_notes:
            notes = '%s\n' % shipment.carrier_notes

        data = {}
        #~ data['portes'] =
        data['bultos'] = packages
        #~ data['volumen'] =
        #~ data['declarado'] =
        #~ data['dninob'] =
        #~ data['fechaentrega'] =
        #~ data['retorno'] =
        #~ data['pod'] =
        #~ data['podobligatorio'] =
        #~ data['remite_plaza'] =
        data['remite_nombre'] = shipment.company.party.name
        data['remite_direccion'] = unaccent(remitente_address.street)
        data['remite_poblacion'] = unaccent(remitente_address.city)
        data['remite_provincia'] = remitente_address.subdivision and remitente_address.subdivision.name or ''
        data['remite_pais'] = remitente_address.country and remitente_address.country.code
        data['remite_cp'] = remitente_address.zip
        data['remite_telefono'] = remitente_address.phone or shipment.company.party.get_mechanism('phone')
        #~ data['remite_movil'] =
        data['remite_email'] = remitente_address.email or shipment.company.party.get_mechanism('email')
        #~ data['remite_departamento'] =
        data['remite_nif'] = shipment.company.party.vat_number
        #~ data['remite_observaciones'] =
        #~ data['destinatario_codigo'] =
        #~ data['destinatario_plaza'] =
        data['destinatario_nombre'] = unaccent(shipment.customer.name)
        data['destinatario_direccion'] = unaccent(shipment.delivery_address.street)
        data['destinatario_poblacion'] = unaccent(shipment.delivery_address.city)
        data['destinatario_provincia'] = shipment.delivery_address.subdivision and unaccent(shipment.delivery_address.subdivision.name) or ''
        data['destinatario_pais'] = shipment.delivery_address.country and shipment.delivery_address.country.code or ''
        data['destinatario_cp'] = shipment.delivery_address.zip
        data['destinatario_telefono'] = shipment.delivery_address.phone or shipment.customer.get_mechanism('phone')
        data['destinatario_movil'] = shipment.delivery_address.mobile or shipment.customer.get_mechanism('mobile')
        data['destinatario_email'] = shipment.delivery_address.email or shipment.customer.get_mechanism('email')
        data['destinatario_observaciones'] = unaccent(notes)
        data['destinatario_att'] = unaccent(remitente_address.name if remitente_address.name else shipment.customer.name)
        #~ data['destinatario_departamento'] =
        #~ data['destinatario_nif'] =
        data['referencia_c'] = code
        #~ data['referencia_0'] = '12345'
        #~ data['importes_debido'] =
        #~ data['seguro'] =
        #~ data['seguro_descripcion'] =
        #~ data['seguro_importe'] =
        #~ data['etiqueta'] =
        #~ data['etiqueta_devolucion'] =
        #~ data['cliente_codigo'] =
        #~ data['cliente_plaza'] =
        #~ data['cliente_agente'] =

        asm_service = asm_services().get(service.code)
        if asm_service:
            data['servicio'] = asm_service['servicio']
            data['horario'] = asm_service['horario']

        if shipment.carrier_cashondelivery and price:
            data['importes_reembolso'] = price

        if weight and hasattr(shipment, 'weight_func'):
            weight = shipment.weight_func
            if weight == 0:
                weight = 1
            if api.weight_api_unit:
                if shipment.weight_uom:
                    print shipment.weight_uom
                    print api.weight_api_unit
                    weight = Uom.compute_qty(
                        shipment.weight_uom, weight, api.weight_api_unit)
                elif api.weight_unit:
                    weight = Uom.compute_qty(
                        api.weight_unit, weight, api.weight_api_unit)
            data['peso'] = str(weight)

        return data

    @classmethod
    def send_asm(self, api, shipments):
        '''
        Send shipments out to asm
        :param api: obj
        :param shipments: list
        Return references, labels, errors
        '''
        pool = Pool()
        CarrierApi = pool.get('carrier.api')
        ShipmentOut = pool.get('stock.shipment.out')

        references = []
        labels = []
        errors = []

        default_service = CarrierApi.get_default_carrier_service(api)
        dbname = Transaction().cursor.dbname

        with Picking(api.username, api.debug) as picking_api:
            for shipment in shipments:
                service = shipment.carrier_service or shipment.carrier.service or default_service
                if not service:
                    message = self.raise_user_error('asm_add_services', {},
                        raise_exception=False)
                    errors.append(message)
                    continue

                if not shipment.delivery_address.country:
                    message = self.raise_user_error('asm_not_country', {},
                        raise_exception=False)
                    errors.append(message)
                    continue

                price = None
                if shipment.carrier_cashondelivery:
                    price = ShipmentOut.get_price_ondelivery_shipment_out(shipment)
                    if not price:
                        message = self.raise_user_error('asm_not_price', {
                                'name': shipment.rec_name,
                                }, raise_exception=False)
                        errors.append(message)
                        continue

                data = self.asm_picking_data(api, shipment, service, price, api.weight)
                reference, label, error = picking_api.create(data)

                if reference:
                    self.write([shipment], {
                        'carrier_tracking_ref': reference,
                        'carrier_service': service,
                        'carrier_delivery': True,
                        'carrier_send_date': ShipmentOut.get_carrier_date(),
                        'carrier_send_employee': ShipmentOut.get_carrier_employee() or None,
                        })
                    logging.getLogger('asm').info(
                        'Send shipment %s' % (shipment.code))
                    references.append(shipment.code)
                else:
                    logging.getLogger('asm').error(
                        'Not send shipment %s.' % (shipment.code))

                if label:
                    with tempfile.NamedTemporaryFile(
                            prefix='%s-asm-%s-' % (dbname, reference),
                            suffix='.pdf', delete=False) as temp:
                        temp.write(decodestring(label))
                    logging.getLogger('asm').info(
                        'Generated tmp label %s' % (temp.name))
                    temp.close()
                    labels.append(temp.name)
                else:
                    message = self.raise_user_error('asm_not_label', {
                            'name': shipment.rec_name,
                            }, raise_exception=False)
                    errors.append(message)
                    logging.getLogger('asm').error(message)

                if error:
                    message = self.raise_user_error('asm_not_send_error', {
                            'name': shipment.rec_name,
                            'error': error,
                            }, raise_exception=False)
                    logging.getLogger('asm').error(message)
                    errors.append(message)

        return references, labels, errors

    @classmethod
    def print_labels_asm(self, api, shipments):
        '''
        Get labels from shipments out from ASM
        Not available labels from ASM API. Not return labels
        '''
        labels = []
        dbname = Transaction().cursor.dbname

        with Picking(api.username, api.debug) as picking_api:
            for shipment in shipments:
                if not shipment.carrier_tracking_ref:
                    logging.getLogger('carrier_send_shipment_asm').error(
                        'Shipment %s has not been sent by ASM.'
                        % (shipment.code))
                    continue

                reference = shipment.carrier_tracking_ref

                data = {}
                data['codigo'] = reference
                label = picking_api.label(data)

                if not label:
                    logging.getLogger('asm').error(
                        'Label for shipment %s is not available from ASM.'
                        % shipment.code)
                    continue
                with tempfile.NamedTemporaryFile(
                        prefix='%s-asm-%s-' % (dbname, reference),
                        suffix='.pdf', delete=False) as temp:
                    temp.write(decodestring(label))
                logging.getLogger('asm').info(
                    'Generated tmp label %s' % (temp.name))
                temp.close()
                labels.append(temp.name)
            self.write(shipments, {'carrier_printed': True})

        return labels
