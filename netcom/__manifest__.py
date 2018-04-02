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
<<<<<<< HEAD
    'version': '0.12002',
=======
    'version': '0.12000',
>>>>>>> 079c0a645d525c588b56bb6fc61dadf37da5c106

    # any module necessary for this one to work correctly
    'depends': ['base','crm','product','stock','sale'],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        'views/views.xml',
        'views/stock_views.xml',
        'views/templates.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}
