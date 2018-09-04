# -*- coding: utf-8 -*-

import time
import xlwt
import base64
from io import BytesIO

from odoo import api, fields, models

class report_payrollregister(models.AbstractModel):
    _name = 'report.netcom_hr_payroll.report_payrollregister'

    @api.model
    def render_html(self, docids, data=None):
        docargs = {
           'doc_ids': self.ids,
           'doc_model': self.model,
           'data': data,
        }
        return self.env['report'].render('netcom_hr_payroll.report_payrollregister', docargs)

    @api.model
    def get_report_values(self, docids, data=None):
        return {
            'doc_ids': [],
            'doc_model': 'payroll.register',
            'data': data,
            'docs': self.env['payroll.register'],
        }

class payroll_reg(models.TransientModel):
    _name = 'payroll.register'
    _description = 'Payroll Register'

    mnths = []
    mnths_total = []
    rules = []
    rules_data = []
    
    total = 0.0
    
    name = fields.Char('Name', required=True,size=140)
    start_date = fields.Date('Start Date', required=True)
    end_date = fields.Date('End Date', required=True)
    employee_ids = fields.Many2many('hr.employee', 'payroll_register_rel', 'payroll_year_id', 'employee_id', 'Employees', required=True)
    rule_ids = fields.Many2many('hr.salary.rule', 'payroll_register_rel_salary', 'reg_id', 'rule_id', 'Salary Rules', required=True)
    xls_output = fields.Boolean('Excel Output', help='Tick if you want to output of report in excel sheet')


    def get_months_tol(self):
        return self.mnths_total

    def get_periods(self, form):
        mnth_name = []
        rules = []  
        rule_ids = form.get('rule_ids', [])  
        if rule_ids:
            for r in self.env['hr.salary.rule'].browse(rule_ids):
                mnth_name.append(r.name)
                rules.append(r.id)
        self.rules = rules
        self.rules_data = mnth_name
        return [mnth_name]

    def get_salary(self, form, emp_id, emp_salary, total_mnths):
        total = 0.0
        cnt = 0
        flag = 0
        for r in self.rules:
            rname = self.env['hr.salary.rule'].browse( r)
            self._cr.execute("select pl.name as name ,pl.total \
                                 from hr_payslip_line as pl \
                                 left join hr_payslip as p on pl.slip_id = p.id \
                                 left join hr_employee as emp on emp.id = p.employee_id \
                                 left join resource_resource as r on r.id = emp.resource_id  \
                                where p.employee_id = %s and pl.salary_rule_id = %s \
                                and (p.date_from >= %s) AND (p.date_to <= %s) \
                                group by pl.total,r.name, pl.name,emp.id",(emp_id, r, form.get('start_date', False), form.get('end_date', False),))
            sal = self._cr.fetchall()
            salary = dict(sal)
            cnt +=1
            flag +=1
            if flag > 8:
                continue
            if rname.name in salary:
                emp_salary.append(salary[rname.name])
                total += salary[rname.name]
                total_mnths[cnt] = total_mnths[cnt] + salary[rname.name]
            else:
                emp_salary.append('')
        
        if len(self.rules) < 9:
            diff = 9 - len(self.rules)
            for x in range(0,diff):
                emp_salary.append('')
        return emp_salary, total, total_mnths

    def get_salary1(self, form, emp_id, emp_salary, total_mnths):
        total = 0.0
        cnt = 0
        flag = 0
        for r in self.rules:
            rname = self.env['hr.salary.rule'].browse( r)
            self._cr.execute("select pl.name as name , pl.total \
                                 from hr_payslip_line as pl \
                                 left join hr_payslip as p on pl.slip_id = p.id \
                                 left join hr_employee as emp on emp.id = p.employee_id \
                                 left join resource_resource as r on r.id = emp.resource_id  \
                                where p.employee_id = %s and pl.salary_rule_id = %s \
                                and (p.date_from >= %s) AND (p.date_to <= %s) \
                                group by pl.total,r.name, pl.name,emp.id",(emp_id, r, form.get('start_date', False), form.get('end_date', False),))

            sal = self._cr.fetchall()
            salary = dict(sal)
            cnt +=1
            flag +=1
            if rname.name in salary:
                emp_salary.append(salary[rname.name])               
                total += salary[rname.name]
                total_mnths[cnt] = total_mnths[cnt] + salary[rname.name]
            else:
                emp_salary.append('')
        return emp_salary, total, total_mnths

    def get_employee(self, form, excel=False):
        emp_salary = []
        salary_list = []
        mnths_total = []
        total_mnths=['Total', 0, 0, 0, 0, 0, 0, 0, 0,0] #only for pdf report!
        emp_obj = self.env['hr.employee']
        emp_ids = form.get('employee_ids', [])
        
        total_excel_months = ['Total',]#for excel report
        for r in range(0, len(self.rules)):
            total_excel_months.append(0)
        employees  = emp_obj.browse(emp_ids)
        for emp_id in employees:
            emp_salary.append(emp_id.name)
            total = 0.0
            if excel:
                emp_salary, total, total_mnths = self.get_salary1(form, emp_id.id, emp_salary, total_mnths=total_excel_months)
            else:
                emp_salary, total, total_mnths = self.get_salary(form, emp_id.id, emp_salary, total_mnths)
            emp_salary.append(total)
            salary_list.append(emp_salary)
            emp_salary = []
        self.mnths_total = total_mnths
        return salary_list

    @api.multi
    def print_report(self):
        """
         To get the date and print the report
         @param self: The object pointer.
         @param cr: A database cursor
         @param uid: ID of the user currently logged in
         @param context: A standard dictionary
         @return: return report
        """
        # if context is None:
        #     context = {}
        datas = {'ids': self._context.get('active_ids', [])}

        res = self.read()
        res = res and res[0] or {}
        datas.update({'form': res})
        
        if datas['form'].get('xls_output', False):
            workbook = xlwt.Workbook()
            sheet = workbook.add_sheet('Payroll Register')
            sheet.row(0).height = 256*3

            title_style = xlwt.easyxf('font: name Times New Roman,bold on, italic on, height 600')
            title_style1 = xlwt.easyxf('font: name Times New Roman,bold on')
            al = xlwt.Alignment()
            al.horz = xlwt.Alignment.HORZ_CENTER
            title_style.alignment = al
            
            sheet.write_merge(0, 0, 5, 9, 'Payroll Register', title_style)
            sheet.write(1, 6, datas['form']['name'], title_style1)
            sheet.write(2, 4, 'From', title_style1)
            sheet.write(2, 5, datas['form']['start_date'], title_style1)
            sheet.write(2, 6, 'To', title_style1)
            sheet.write(2, 7, datas['form']['end_date'], title_style1)
            main_header = self.get_periods(datas['form'])
            
            # Add the PFA LIST
            pfa_list = []
            zip_pfa_list = []
            pfa_dict = {}
            pfa_obj = self.env['pfa']
            pfa_ids = pfa_obj.search([])
            pfas = pfa_ids
            pfa_list = ["Pension - " + pfa.name for pfa in pfas]            
            zip_pfa_list = [0.0 for pfa in pfas] # Creates an empty list filled with zeros
            
            pfa_dict = dict(zip(pfa_list,zip_pfa_list))
            
            bf_pfa_list = ['Name'] + main_header[0]
            count_bf_pfa_list = len(bf_pfa_list)            
            af_pfa_list = ['Total']            
            comp_list = bf_pfa_list +  af_pfa_list + pfa_list
            
            row = self.render_header(sheet, comp_list, first_row=5)
            emp_datas = self.get_employee(datas['form'], excel=True)
            
            emp_ids = datas['form']['employee_ids']
            employee_obj = self.env['hr.employee']
            employees = employee_obj.browse(emp_ids)
            
            # Search for the Pension Field
            inds = []               
            for i, ele in enumerate(comp_list):
                if "Employee's Pension Contribution"  == ele:
                    inds.append(i)
            
            if inds :                    
                for emp_data in emp_datas :
                    emp_ids = employee_obj.search([('name','=',emp_data[0])])
                    pen_comp = emp_ids[0].pfa_id
                    thevalue = emp_data[inds[0]]
                    if not thevalue:
                        thevalue = 0.0
                    
                    data_len = len(emp_data)
                    
                    #Pad the list with empty spaces
                    for i in range(0,len(pfa_list)) :            
                        emp_data.insert(data_len,'')
                         
                    if pen_comp :
                        # Search for the index of the column
                        ind = []
                        for i, ele in enumerate(comp_list):
                            if "Pension - " + pen_comp == ele:
                                ind.append(i)
                        try:
                            emp_data[ind[0]] = float(thevalue)
                        except Exception as e:
                            pass
                            # emp_data[0] = 0
                        # emp_data[ind[0]] = float(thevalue)                   
                        pfa_total = pfa_dict.get("Pension - " + pen_comp) or 0.0
                        pfa_dict["Pension - " + pen_comp] = pfa_total + thevalue
                    
            value_style = xlwt.easyxf('font: name Helvetica', num_format_str = '#,##0.00')
            cell_count = 0
            for value in emp_datas:
                for v in value:
                    sheet.write(row,cell_count,v,value_style)
                    cell_count += 1
                row += 1
                cell_count = 0
            sheet.write(row+1, 0, 'Total',value_style)
            total_datas = self.get_months_tol()
            
            cell_count = 1
            for value in [total_datas]:
                row += 1
                for v in value[1:]:
                    sheet.write(row,cell_count,v,value_style)
                    cell_count += 1
                # cell_count = 0

            total = self.get_total()
            sheet.write(row,cell_count,total,value_style)
            cell_count = 0

            col = 0
            ind = []            
            for pfa in pfa_list :
                for i, ele in enumerate(comp_list):
                    if pfa == ele:
                        pfa_total = pfa_dict.get(pfa)
                        col = i
                        sheet.write(row,col,pfa_total,value_style)
            row += 1
            
            stream = BytesIO()
            workbook.save(stream)
            stream.seek(0)
            result = base64.b64encode(stream.read()) 
            base_url = self.env['ir.config_parameter'].get_param('web.base.url')
            attachment_obj = self.env['ir.attachment']
            attachment_id = attachment_obj.create({'name': self.name+'.xlsx', 'datas_fname': self.name+'.xlsx', 'datas': result})
            download_url = '/web/content/' + str(attachment_id.id) + '?download=true'
            return {
                    "type": "ir.actions.act_url",
                    "url": str(base_url) + str(download_url),
                    "target": "self",
                }
        data = {'data': datas}
        return self.env.ref('netcom_hr_payroll.action_report_payroll_register').report_action(self, data=datas, config=False)
        
    def render_header(self, ws, fields, first_row=0):
        header_style = xlwt.easyxf('font: name Helvetica,bold on')
        col = 0
        for hdr in fields:
            ws.write(first_row, col, hdr, header_style)
            col += 1
        return first_row + 2

    def get_total(self):
        for count in range(1, len(self.mnths_total)):
          if not isinstance(self.mnths_total[count], float) and not isinstance(self.mnths_total[count], int):
              continue
          self.total += self.mnths_total[count]
        return self.total