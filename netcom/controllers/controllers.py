# -*- coding: utf-8 -*-
from odoo import http

# class Netcom(http.Controller):
#     @http.route('/netcom/netcom/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/netcom/netcom/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('netcom.listing', {
#             'root': '/netcom/netcom',
#             'objects': http.request.env['netcom.netcom'].search([]),
#         })

#     @http.route('/netcom/netcom/objects/<model("netcom.netcom"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('netcom.object', {
#             'object': obj
#         })