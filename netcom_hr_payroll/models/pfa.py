# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class pfa(models.Model):
    _name = 'pfa'

    name = fields.Char('Name of PFA', size=128, required=True)
    contact_address = fields.Text('Contact Address')
    email = fields.Char('Email', size=128,)
    name_person = fields.Char('Name of Contact Person', size=64)
    notes = fields.Text('Notes')
    phone = fields.Char('Phone', size=128)
    code = fields.Char('PFA ID', size=64, required=False)