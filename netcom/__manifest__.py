# -*- coding: utf-8 -*-
{
    'name': "Netcom",

    'summary': """
        Netcom Modules""",

    'description': """
        Long description of module's purpose
    """,

    'author': "MCEE Solutions",
    'website': "http://www.mceesolutions.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/odoo/addons/base/module/module_data.xml
    # for the full list
    'category': 'Netcom',
    'version': '0.129999999999999999999994',


    # any module necessary for this one to work correctly
    'depends': ['base','account_budget','crm','sale_crm','hr_expense', 'hr_recruitment','mrp',
    'hr','purchase','sale_subscription','product','stock','sale','mail','hr_holidays',
    'purchase_requisition'],

    # always loaded
    'data': [
        'security/netcom_security.xml',
        'security/ir.model.access.csv',
        'data/data.xml',
        'views/views.xml',
        'views/stock_views.xml',
        'views/templates.xml',
        'views/website_netcom_hr_recruitment_template.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}
