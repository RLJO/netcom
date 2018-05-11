# -*-coding:utf-8-*-
from odoo import models, fields, api

class HRContract(models.Model):
	_inherit = 'hr.contract'

	pen_contrib = fields.Float('Pension Contribution', default=8.0)