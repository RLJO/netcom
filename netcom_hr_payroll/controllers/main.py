
import json
import werkzeug
import werkzeug.wsgi
from odoo import http
import time
import werkzeug.utils
import werkzeug.wrappers
from odoo.http import request
from collections import OrderedDict
from odoo.tools.safe_eval import safe_eval
from werkzeug.urls import url_decode, iri_to_uri
from odoo.addons.web.controllers.main import ReportController
from odoo.tools import crop_image, topological_sort, html_escape, pycompat
from odoo.http import content_disposition, dispatch_rpc, request, \
    serialize_exception as _serialize_exception, Response




class ReportControllerExtended(ReportController):

    @http.route(['/report/download'], type='http', auth="user")
    def report_download(self, data, token):
        """This function is used by 'qwebactionmanager.js' in order to trigger the download of
        a pdf/controller report.

        :param data: a javascript array JSON.stringified containg report internal url ([0]) and
        type [1]
        :returns: Response with a filetoken cookie and an attachment header
        """
        requestcontent = json.loads(data)
        url, type = requestcontent[0], requestcontent[1]
        try:
            if type == 'qweb-pdf':
                reportname = url.split('/report/pdf/')[1].split('?')[0]

                docids = None
                active_model = ''
                NewReportName = ''
                if '/' in reportname:
                    reportname, docids = reportname.split('/')

                if docids:
                    # Generic report:
                    response = self.report_routes(reportname, docids=docids, converter='pdf')
                else:
                    # Particular report:
                    data = url_decode(url.split('?')[1]).items()  # decoding the args represented in JSON

                    dictData = dict(data)
                    active_model = json.loads(dictData.get('context')).get('active_model')
                    NewReportName = json.loads(dictData.get('options')).get('form').get('name')
                    response = self.report_routes(reportname, converter='pdf', **dictData)

                report = request.env['ir.actions.report']._get_report_from_name(reportname)
                filename = "%s.%s" % (report.name, "pdf")

                if active_model == 'payroll.register':
                    filename = "%s.%s" % (NewReportName, "pdf")

                if docids:
                    ids = [int(x) for x in docids.split(",")]
                    obj = request.env[report.model].browse(ids)
                    if report.print_report_name and not len(obj) > 1:
                        report_name = safe_eval(report.print_report_name, {'object': obj, 'time': time})
                        filename = "%s.%s" % (report_name, "pdf")
                    if report.model == 'payroll.register':
                        filename = "%s.%s" % (obj.name, "pdf")
                response.headers.add('Content-Disposition', content_disposition(filename))
                response.set_cookie('fileToken', token)
                return response
            else:
                return
        except Exception as e:
            se = _serialize_exception(e)
            error = {
                'code': 200,
                'message': "Odoo Server Error",
                'data': se
            }
            return request.make_response(html_escape(json.dumps(error)))