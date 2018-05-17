#-*- coding:utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models


class NetcomPayslipDetailsReport(models.AbstractModel):
    _name = 'report.netcom_hr_payroll.report_netcompayslipdetails'
    
    
    def _get_payslips(self, payslip_ids):
        payslip_obj = self.env['hr.payslip']
        payslips = payslip_obj.search([('id','in',payslip_ids)])
        return payslips

    def _get_payslip_lines(self, payslip_lines):       
        PayslipLine = self.env['hr.payslip.line']
        RuleCateg = self.env['hr.salary.rule.category']

        def get_recursive_parent(current_rule_category, rule_categories=None):
            if rule_categories:
                rule_categories = current_rule_category | rule_categories
            else:
                rule_categories = current_rule_category

            if current_rule_category.parent_id:
                return get_recursive_parent(current_rule_category.parent_id, rule_categories)
            else:
                return rule_categories

        res = {}
        result = {}

        if payslip_lines:
            self.env.cr.execute("""
                SELECT pl.id, pl.category_id, pl.slip_id FROM hr_payslip_line as pl
                LEFT JOIN hr_salary_rule_category AS rc on (pl.category_id = rc.id)
                WHERE pl.id in %s
                GROUP BY rc.parent_id, pl.sequence, pl.id, pl.category_id
                ORDER BY pl.sequence, rc.parent_id""",
                (tuple(payslip_lines.ids),))
            for x in self.env.cr.fetchall():
                result.setdefault(x[2], {})
                result[x[2]].setdefault(x[1], [])
                result[x[2]][x[1]].append(x[0])
            for payslip_id, lines_dict in result.iteritems():
                res.setdefault(payslip_id, [])
                for rule_categ_id, line_ids in lines_dict.iteritems():
                    rule_categories = RuleCateg.browse(rule_categ_id)
                    lines = PayslipLine.browse(line_ids)
                    level = 0
                    """for parent in get_recursive_parent(rule_categories):
                        res[payslip_id].append({
                            'rule_category': parent.code,
                            'name': parent.name,
                            'code': parent.code,
                            'level': level,
                            'total': sum(lines.mapped('total')),
                        })
                        level += 1"""
                    for line in lines:
                        res[payslip_id].append({
                            'rule_category': line.category_id.code,
                            'name': line.name,
                            'code': line.code,
                            'amount': line.amount,
                            'total': line.total,
                            'level': level
                        })
        return res


    @api.model
    def render_html(self, docids, data=None):
        payslips = self.env['hr.payslip'].browse(docids[0])
        docargs = {
            'doc_ids': docids,
            'doc_model': 'hr.payslip',
            'docs': payslips,
            'data': data,
            'get_payslip': self._get_payslips(payslips.ids),
            'get_payslip_lines': self._get_payslip_lines(payslips.mapped('details_by_salary_rule_category').filtered(lambda r: r.appears_on_payslip)),
        }
        return self.env['report'].render('netcom_hr_payroll.report_netcompayslipdetails', docargs)
