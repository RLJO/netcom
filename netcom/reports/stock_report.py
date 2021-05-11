# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

#
# Please note that these reports are not multi-currency !!!
#

from odoo import api, fields, models, tools


class NRCStockReport(models.Model):
    _name = "nrc.stock.report"
    _description = "Stock Report"
    _auto = False
    _order = 'date_order desc, price_total desc'

    

