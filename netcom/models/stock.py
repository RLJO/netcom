# -*- coding: utf-8 -*-

from odoo import models, fields, api



class Picking(models.Model):
    _name = "stock.picking"
    _inherit = 'stock.picking'


