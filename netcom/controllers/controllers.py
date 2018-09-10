# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

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

class Hrrecruitment(http.Controller):
    @http.route('/jobs/apply/<model("hr.job"):job>', type='http', auth="public", website=True)
    
    def jobs_apply(self, job, **kwargs):
        error = {}
        default = {}
        # country = env['res.country']
        nationality = http.request.env['res.country'].sudo().search([])
        
        if 'website_hr_recruitment_error' in request.session:
            error = request.session.pop('website_hr_recruitment_error')
            default = request.session.pop('website_hr_recruitment_default')
        return request.render("website_hr_recruitment.apply", {
            'job': job,
            'error': error,
            'default': default,
            'nationality': nationality,
        })