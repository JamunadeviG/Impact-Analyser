// Copyright (c) 2026, Impact Analyser and contributors
// For license information, please see license.txt

frappe.ui.form.on('Dead Code Eliminator', {
	onload: function(frm) {
		if (!frm.doc.target_app) {
			frm.set_value('target_app', 'airplane_mode');
		}
	},

	refresh: function(frm) {
		// Primary Action Button: Scan Entire App
		frm.add_custom_button(__('⚡ Scan Entire App'), function() {
			const appName = frm.doc.target_app || 'airplane_mode';

			frappe.show_alert({
				message: __('Traversing all DocTypes, .py, and .js files in ' + appName + '...'),
				indicator: 'blue'
			});

			frm.call({
				doc: frm.doc,
				method: 'run_analysis',
				freeze: true,
				freeze_message: __('Analyzing AST & Enforcing Frappe Framework Guardrails...'),
				callback: function(r) {
					if (!r.exc && r.message) {
						const msg = r.message;
						frappe.show_alert({
							message: __(
								'Scan Finished! ' + (msg.total_files || 0) + ' files scanned, ' +
								(msg.total_dead_items || 0) + ' dead candidates identified (' +
								(msg.safe_to_remove || 0) + ' safe to eliminate).'
							),
							indicator: 'green'
						});
						frm.refresh();
					}
				}
			});
		}).addClass('btn-primary');

		// Filter Buttons for Inventory Table
		if (frm.doc.inventory && frm.doc.inventory.length > 0) {
			frm.add_custom_button(__('Show Low Risk Only'), function() {
				frm.fields_dict['inventory'].grid.filter('risk_level', '=', 'Low');
			}, __('Filter Results'));

			frm.add_custom_button(__('Show All'), function() {
				frm.fields_dict['inventory'].grid.clear_filter();
			}, __('Filter Results'));
		}
	}
});


a