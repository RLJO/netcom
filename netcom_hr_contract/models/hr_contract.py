# -*-coding:utf-8-*-
from odoo import models, fields

class Contract(models.Model):
	_inherit = 'hr.contract'

	pen_contrib = fields.Float(string='Pension Contribution', default=8.0)