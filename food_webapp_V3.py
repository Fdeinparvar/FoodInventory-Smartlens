from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify
import sqlite3
import os
from datetime import datetime
import requests
import base64
import json

# Import API key from config
try:
    from config import ANTHROPIC_API_KEY
except ImportError:
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', 'ANTHROPIC_API_KEY')

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'food.db')

# Anthropic API configuration
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Needed for flash messages
app.config['TESTING'] = True

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize the database with settings table and default tables"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Create settings table to store table configurations
    cur.execute('''
        CREATE TABLE IF NOT EXISTS table_settings (
            table_id TEXT PRIMARY KEY,
            table_name TEXT NOT NULL,
            columns TEXT NOT NULL,
            display_columns TEXT NOT NULL,
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Check if display_order column exists, if not add it
    try:
        cur.execute('SELECT display_order FROM table_settings LIMIT 1')
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        cur.execute('ALTER TABLE table_settings ADD COLUMN display_order INTEGER DEFAULT 0')
        # Update existing records with sequential order, ensuring pantry is first
        cur.execute('SELECT table_id FROM table_settings ORDER BY table_id')
        existing_tables = cur.fetchall()
        order = 0
        # Put pantry first if it exists
        for row in existing_tables:
            if row['table_id'] == 'pantry':
                cur.execute('UPDATE table_settings SET display_order = ? WHERE table_id = ?', (order, row['table_id']))
                order += 1
        # Then add the rest
        for row in existing_tables:
            if row['table_id'] != 'pantry':
                cur.execute('UPDATE table_settings SET display_order = ? WHERE table_id = ?', (order, row['table_id']))
                order += 1
    
    # Check if we have any tables configured
    cur.execute('SELECT COUNT(*) FROM table_settings')
    if cur.fetchone()[0] == 0:
        # Insert default tables
        default_tables = [
            ('pantry', 'Pantry',
             json.dumps(['item', 'dateofpurchase', 'amount']),
             json.dumps(['Item', 'Date of Purchase', 'Amount']), 0),
            ('basement_freezer', 'Basement Freezer', 
             json.dumps(['item', 'dateofpurchase', 'weight', 'amount']),
             json.dumps(['Item', 'Date of Purchase', 'Weight', 'Amount']), 1)
        ]
        
        for table_id, table_name, columns, display_columns, display_order in default_tables:
            cur.execute('''
                INSERT INTO table_settings (table_id, table_name, columns, display_columns, display_order)
                VALUES (?, ?, ?, ?, ?)
            ''', (table_id, table_name, columns, display_columns, display_order))
            
            # Create the actual table
            columns_list = json.loads(columns)
            # Escape column names with square brackets to handle SQL keywords
            escaped_columns = [f'[{col}] TEXT' for col in columns_list]
            create_table_sql = f'''
                CREATE TABLE IF NOT EXISTS {table_id} (
                    {', '.join(escaped_columns)}
                )
            '''
            cur.execute(create_table_sql)
    
    conn.commit()
    conn.close()
    
    # Ensure pantry is always first for existing databases
    ensure_pantry_first()

def ensure_pantry_first():
    """Ensure pantry tab is always displayed first"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Check if pantry exists
        cur.execute('SELECT display_order FROM table_settings WHERE table_id = ?', ('pantry',))
        pantry_result = cur.fetchone()
        
        if pantry_result:
            pantry_order = pantry_result[0]
            # If pantry is not first (order 0), reorder everything
            if pantry_order != 0:
                # Get current order of all tables
                cur.execute('SELECT table_id, display_order FROM table_settings ORDER BY display_order')
                tables = cur.fetchall()
                
                # Reorder: pantry first, then others
                new_order = 0
                # Set pantry to 0
                cur.execute('UPDATE table_settings SET display_order = ? WHERE table_id = ?', (0, 'pantry'))
                new_order = 1
                
                # Set others in their current relative order
                for table in tables:
                    if table['table_id'] != 'pantry':
                        cur.execute('UPDATE table_settings SET display_order = ? WHERE table_id = ?', 
                                   (new_order, table['table_id']))
                        new_order += 1
                
                conn.commit()
    except Exception as e:
        print(f"Error ensuring pantry is first: {e}")
    finally:
        conn.close()

def get_tables_config():
    """Get table configurations from database"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM table_settings ORDER BY display_order, table_id')
    rows = cur.fetchall()
    conn.close()
    
    tables = {}
    for row in rows:
        tables[row['table_id']] = {
            'name': row['table_name'],
            'columns': json.loads(row['columns']),
            'display_columns': json.loads(row['display_columns']),
            'display_order': row['display_order']
        }
    return tables

def create_table(table_id, table_name, columns, display_columns):
    """Create a new table in the database"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Get the next display order
        cur.execute('SELECT MAX(display_order) FROM table_settings')
        max_order = cur.fetchone()[0]
        next_order = (max_order or -1) + 1
        
        # Add to settings table
        cur.execute('''
            INSERT INTO table_settings (table_id, table_name, columns, display_columns, display_order)
            VALUES (?, ?, ?, ?, ?)
        ''', (table_id, table_name, json.dumps(columns), json.dumps(display_columns), next_order))
        
        # Create the actual table
        # Escape column names with square brackets to handle SQL keywords
        escaped_columns = [f'[{col}] TEXT' for col in columns]
        create_table_sql = f'''
            CREATE TABLE {table_id} (
                {', '.join(escaped_columns)}
            )
        '''
        cur.execute(create_table_sql)
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def update_table(table_id, table_name, columns, display_columns):
    """Update an existing table structure"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Get current columns
        cur.execute('SELECT columns FROM table_settings WHERE table_id = ?', (table_id,))
        old_columns = json.loads(cur.fetchone()['columns'])
        
        # Update settings table
        cur.execute('''
            UPDATE table_settings 
            SET table_name = ?, columns = ?, display_columns = ?
            WHERE table_id = ?
        ''', (table_name, json.dumps(columns), json.dumps(display_columns), table_id))
        
        # Handle table structure changes
        if set(columns) != set(old_columns):
            # Create new table with new structure
            temp_table = f"{table_id}_temp"
            # Escape column names with square brackets to handle SQL keywords
            escaped_columns = [f'[{col}] TEXT' for col in columns]
            create_table_sql = f'''
                CREATE TABLE {temp_table} (
                    {', '.join(escaped_columns)}
                )
            '''
            cur.execute(create_table_sql)
            
            # Copy data from old table to new table
            common_columns = [col for col in columns if col in old_columns]
            if common_columns:
                # Escape column names with square brackets
                escaped_columns = [f'[{col}]' for col in common_columns]
                copy_sql = f'''
                    INSERT INTO {temp_table} ({', '.join(escaped_columns)})
                    SELECT {', '.join(escaped_columns)} FROM {table_id}
                '''
                cur.execute(copy_sql)
            
            # Drop old table and rename new table
            cur.execute(f'DROP TABLE {table_id}')
            cur.execute(f'ALTER TABLE {temp_table} RENAME TO {table_id}')
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def delete_table(table_id):
    """Delete a table and its configuration"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Delete from settings table
        cur.execute('DELETE FROM table_settings WHERE table_id = ?', (table_id,))
        
        # Drop the actual table
        cur.execute(f'DROP TABLE IF EXISTS {table_id}')
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def update_table_order(table_orders):
    """Update the display order of tables"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        for table_id, new_order in table_orders.items():
            cur.execute('''
                UPDATE table_settings 
                SET display_order = ? 
                WHERE table_id = ?
            ''', (new_order, table_id))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# Initialize database on startup
init_database()

TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Food Inventory Management</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <link href="https://cdn.jsdelivr.net/npm/cropperjs@1.5.13/dist/cropper.min.css" rel="stylesheet"/>
    <style>
        .editable-cell {
            cursor: pointer;
            background: #f8f9fa;
            transition: background 0.2s;
        }
        .editable-cell:hover {
            background: #e2e6ea;
        }
        .editable-input {
            min-width: 60px;
            width: 100%;
            box-sizing: border-box;
        }
        
        /* Drag and drop styles */
        .nav-item.drag-over {
            border-left: 3px solid #007bff;
            background-color: #f8f9fa;
        }
        
        .nav-item[draggable="true"] {
            cursor: move;
        }
        
        .nav-item[draggable="true"]:hover .drag-handle {
            opacity: 1 !important;
        }
        
        .drag-handle {
            user-select: none;
            -webkit-user-select: none;
            -moz-user-select: none;
            -ms-user-select: none;
        }
    </style>
</head>
<body class="bg-light">
<div class="container py-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1>Food Inventory Management</h1>
        <a href="{{ url_for('settings') }}" class="btn btn-outline-secondary">Settings</a>
    </div>
    
    <!-- Capture Barcode Button and Modal -->
    <div class="mb-3">
        <button class="btn btn-warning" id="capture-barcode-btn">Smart Lens</button>
        <div class="form-check form-check-inline ms-3">
            <input class="form-check-input" type="radio" name="analysisMode" id="sameItemMode" value="same" checked>
            <label class="form-check-label" for="sameItemMode">Same Item (Multiple Angles)</label>
        </div>
        <div class="form-check form-check-inline">
            <input class="form-check-input" type="radio" name="analysisMode" id="multipleItemsMode" value="multiple">
            <label class="form-check-label" for="multipleItemsMode">Multiple Items</label>
        </div>
    </div>
    <input type="file" accept="image/*" capture="environment" id="barcode-file-input" style="display:none;" multiple>
    <div class="modal fade" id="barcodeImageModal" tabindex="-1" aria-labelledby="barcodeImageModalLabel" aria-hidden="true">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="barcodeImageModalLabel">Product Analysis</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div id="image-gallery" class="mb-3" style="display:none;">
              <h6>Captured Images:</h6>
              <div id="image-container" class="d-flex flex-wrap gap-2"></div>
              <div class="mt-2">
                <button class="btn btn-sm btn-outline-primary" id="add-more-images">Add More Images</button>
                <button class="btn btn-primary" id="analyze-images" style="display:none;">Analyze Images</button>
              </div>
            </div>
            <div id="barcode-decode-result" class="mt-3"></div>
            <div id="add-to-inventory" class="mt-3" style="display:none;">
              <h6>Add to Inventory:</h6>
              <form id="inventory-form">
                                <div class="row">
                  <div class="col-md-6">
                    <label class="form-label">Location:</label>
                    <select class="form-select" id="inventory-location" required disabled>
                      {% for table_id, table_config in tables.items() %}
                      <option value="{{ table_id }}" {% if table_id == active_tab %}selected{% endif %}>{{ table_config.name }}</option>
                      {% endfor %}
                    </select>
                  </div>
                  </div>
                <div class="row mt-2" id="dynamic-fields">
                  <div class="col-md-6">
                    <label class="form-label">Item Name:</label>
                    <input type="text" class="form-control" id="inventory-item" required>
                  </div>
                  <div class="col-md-3">
                    <label class="form-label">Amount:</label>
                    <input type="number" class="form-control" id="inventory-amount" value="1" min="1" required>
                  </div>
                </div>
                <button type="submit" class="btn btn-success mt-3">Add to Inventory</button>
                <button type="button" class="btn btn-primary mt-3 ms-2" id="done-button" style="display:none;">Done</button>
              </form>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Tab Navigation -->
    <ul class="nav nav-tabs mb-4" id="inventoryTabs" role="tablist">
        {% for table_id, table_config in tables.items() %}
        <li class="nav-item" role="presentation" draggable="true" data-table-id="{{ table_id }}">
            <a class="nav-link {% if active_tab == table_id %}active{% endif %}" 
               href="{{ url_for('index', tab=table_id) }}" 
               role="tab">
                {{ table_config.name }}
                <span class="drag-handle ms-2" style="cursor: move; opacity: 0.5;">⋮⋮</span>
            </a>
        </li>
        {% endfor %}
    </ul>
    
    <!-- Tab Content -->
    <div class="tab-content">
        <div class="tab-pane fade show active">
            <form class="row g-3 mb-4" method="get" action="{{ url_for('index', tab=active_tab) }}">
                <input type="hidden" name="tab" value="{{ active_tab }}">
                <div class="col-auto">
                    <input type="text" name="search" class="form-control" placeholder="Search item..." value="{{ request.args.get('search', '') }}">
                </div>
                <div class="col-auto">
                    <select name="order" class="form-select">
                        <option value="desc" {% if request.args.get('order', 'desc') == 'desc' %}selected{% endif %}>Newest First</option>
                        <option value="asc" {% if request.args.get('order') == 'asc' %}selected{% endif %}>Oldest First</option>
                    </select>
                </div>
                <div class="col-auto">
                    <button type="submit" class="btn btn-primary">Apply</button>
                </div>
            </form>
            
            {% with messages = get_flashed_messages() %}
              {% if messages %}
                <div class="alert alert-info">{{ messages[0] }}</div>
              {% endif %}
            {% endwith %}
            
            <table class="table table-bordered table-striped">
                <thead>
                    <tr>
                        {% for col in display_columns %}
                        <th>{{ col }}</th>
                        {% endfor %}
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in items %}
                    <tr>
                        {% for col in columns %}
                        <td class="editable-cell" 
                            data-rowid="{{ row['rowid'] }}" 
                            data-column="{{ col }}"
                            data-value="{{ row[col] }}">
                            <span class="editable-display">{{ row[col] }}</span>
                            {% if col == 'amount' or col == 'count' %}
                                <input type="number" class="editable-input form-control form-control-sm" 
                                       value="{{ row[col] }}" 
                                       style="display:none;"
                                       min="0" step="1">
                            {% elif 'date' in col.lower() %}
                                <input type="date" class="editable-input form-control form-control-sm" 
                                       value="{{ row[col] }}" 
                                       style="display:none;">
                            {% else %}
                                <input type="text" class="editable-input form-control form-control-sm" 
                                       value="{{ row[col] }}" 
                                       style="display:none;">
                            {% endif %}
                        </td>
                        {% endfor %}
                        <td>
                            <a href="{{ url_for('edit_item', tab=active_tab, rowid=row['rowid']) }}" class="btn btn-sm btn-primary">Edit</a>
                            <a href="{{ url_for('delete_item', tab=active_tab, rowid=row['rowid']) }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete this item?');">Delete</a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            <a href="{{ url_for('add_item', tab=active_tab) }}" class="btn btn-success">Add New Item</a>
        </div>
    </div>
</div>

<script src="https://unpkg.com/@zxing/library@0.18.6/umd/index.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
    document.addEventListener('DOMContentLoaded', function() {
        const captureBtn = document.getElementById('capture-barcode-btn');
        const fileInput = document.getElementById('barcode-file-input');
        const modalElem = document.getElementById('barcodeImageModal');
        const resultElem = document.getElementById('barcode-decode-result');
        const addToInventoryDiv = document.getElementById('add-to-inventory');
        const inventoryForm = document.getElementById('inventory-form');
        const locationSelect = document.getElementById('inventory-location');
        const dynamicFields = document.getElementById('dynamic-fields');
        const imageGallery = document.getElementById('image-gallery');
        const imageContainer = document.getElementById('image-container');
        const addMoreImagesBtn = document.getElementById('add-more-images');
        const analyzeImagesBtn = document.getElementById('analyze-images');
        const doneButton = document.getElementById('done-button');
        let bsModal;
        let capturedImages = [];

        // Drag and drop functionality for tabs
        const tabList = document.getElementById('inventoryTabs');
        let draggedElement = null;

        // Add drag event listeners to all tab items
        function initializeDragAndDrop() {
            const tabItems = tabList.querySelectorAll('.nav-item');
            
            tabItems.forEach(item => {
                item.addEventListener('dragstart', handleDragStart);
                item.addEventListener('dragend', handleDragEnd);
                item.addEventListener('dragover', handleDragOver);
                item.addEventListener('drop', handleDrop);
                item.addEventListener('dragenter', handleDragEnter);
                item.addEventListener('dragleave', handleDragLeave);
            });
        }

        function handleDragStart(e) {
            draggedElement = this;
            this.style.opacity = '0.5';
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/html', this.outerHTML);
        }

        function handleDragEnd(e) {
            this.style.opacity = '';
            draggedElement = null;
        }

        function handleDragOver(e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        }

        function handleDragEnter(e) {
            e.preventDefault();
            this.classList.add('drag-over');
        }

        function handleDragLeave(e) {
            this.classList.remove('drag-over');
        }

        function handleDrop(e) {
            e.preventDefault();
            this.classList.remove('drag-over');
            
            if (draggedElement !== this) {
                const allTabs = Array.from(tabList.querySelectorAll('.nav-item'));
                const draggedIndex = allTabs.indexOf(draggedElement);
                const droppedIndex = allTabs.indexOf(this);
                
                // Reorder the tabs
                if (draggedIndex < droppedIndex) {
                    this.parentNode.insertBefore(draggedElement, this.nextSibling);
                } else {
                    this.parentNode.insertBefore(draggedElement, this);
                }
                
                // Update the order in the database
                updateTabOrder();
            }
        }

        function updateTabOrder() {
            const tabItems = tabList.querySelectorAll('.nav-item');
            const tableOrders = {};
            
            tabItems.forEach((item, index) => {
                const tableId = item.getAttribute('data-table-id');
                if (tableId) {
                    tableOrders[tableId] = index;
                }
            });
            
            fetch('/update_table_order', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ table_orders: tableOrders })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    console.log('Tab order updated successfully');
                } else {
                    console.error('Error updating tab order:', data.error);
                }
            })
            .catch(error => {
                console.error('Error updating tab order:', error);
            });
        }

        // Initialize drag and drop when page loads
        initializeDragAndDrop();

        // Set today's date as default for any date fields
        function setDefaultDates() {
            const dateInputs = document.querySelectorAll('input[type="date"]');
            dateInputs.forEach(input => {
                if (!input.value) {
                    input.value = new Date().toISOString().split('T')[0];
                }
            });
        }
        
        // Function to update form fields based on selected table
        function updateFormFields(tableId) {
            console.log('Updating form fields for table:', tableId);
            fetch(`/get_table_config/${tableId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        console.log('Table config:', data);
                        const columns = data.columns;
                        let html = '';
                        
                        columns.forEach((col, index) => {
                            const colClass = index % 2 === 0 ? 'col-md-6' : 'col-md-3';
                            let inputType = 'text';
                            let required = col === 'item' ? 'required' : '';
                            let min = '';
                            let value = '';
                            
                            if (col === 'amount' || col === 'count') {
                                inputType = 'number';
                                min = 'min="1"';
                                value = 'value="1"';
                            } else if (col.toLowerCase().includes('date')) {
                                inputType = 'date';
                                // Only default purchase date fields
                                if (col.toLowerCase().includes('purchase')) {
                                    value = 'value="' + new Date().toISOString().split('T')[0] + '"';
                                }
                            }
                            
                            html += `
                                <div class="${colClass}">
                                    <label class="form-label">${data.display_columns[index]}:</label>
                                    <input type="${inputType}" class="form-control" id="inventory-${col}" ${required} ${min} ${value}>
                                </div>
                            `;
                        });
                        
                        dynamicFields.innerHTML = html;
                        console.log('Form fields updated with HTML:', html);
                    }
                })
                .catch(error => {
                    console.error('Error updating form fields:', error);
                    dynamicFields.innerHTML = '<div class="text-danger">Error loading form fields</div>';
                });
        }

        // Initial form setup - will be called when modal opens
        // updateFormFields(locationSelect.value);

        captureBtn.addEventListener('click', function() {
            fileInput.click();
        });

        fileInput.addEventListener('change', function(event) {
            const files = Array.from(event.target.files);
            console.log('Files selected:', files.length, files);
            
            if (files.length > 0) {
                let isAddingMore = capturedImages.length > 0;
                
                if (!isAddingMore) {
                    // First time selecting files - reset everything
                    capturedImages = [];
                    imageContainer.innerHTML = '';
                    resultElem.innerHTML = '';
                    addToInventoryDiv.style.display = 'none';
                }
                
                let processedFiles = 0;
                let startIndex = isAddingMore ? capturedImages.length : 0;
                
                files.forEach((file, index) => {
                    console.log('Processing file:', startIndex + index, file.name);
                    const reader = new FileReader();
                    reader.onload = function(e) {
                        console.log('File loaded:', startIndex + index, file.name);
                        capturedImages.push(e.target.result);
                        addImageToGallery(e.target.result, startIndex + index);
                        processedFiles++;
                        
                        console.log('Processed files:', processedFiles, 'of', files.length);
                        
                        if (processedFiles === files.length) {
                            if (!isAddingMore) {
                                // First time - open modal
                                console.log('All files processed, opening modal');
                                
                                // Set location to current tab and disable it
                                locationSelect.value = '{{ active_tab }}';
                                locationSelect.disabled = true;
                                
                                bsModal = new bootstrap.Modal(modalElem);
                                bsModal.show();
                                imageGallery.style.display = 'block';
                                analyzeImagesBtn.style.display = 'inline-block';
                                
                                // Reset and update form fields after modal is shown
                                setTimeout(() => {
                                    updateFormFields(locationSelect.value);
                                }, 100);
                            } else {
                                // Adding more - show analyze button again
                                console.log('All additional files processed');
                                analyzeImagesBtn.style.display = 'inline-block';
                            }
                        }
                    };
                    reader.onerror = function() {
                        console.error('Error reading file:', startIndex + index, file.name);
                        processedFiles++;
                        if (processedFiles === files.length) {
                            if (!isAddingMore) {
                                // Still open modal even if some files failed
                                // Set location to current tab and disable it
                                locationSelect.value = '{{ active_tab }}';
                                locationSelect.disabled = true;
                                
                                bsModal = new bootstrap.Modal(modalElem);
                                bsModal.show();
                                imageGallery.style.display = 'block';
                                analyzeImagesBtn.style.display = 'inline-block';
                                setTimeout(() => {
                                    updateFormFields(locationSelect.value);
                                }, 100);
                            }
                        }
                    };
                    reader.readAsDataURL(file);
                });
            }
        });
        
        addMoreImagesBtn.addEventListener('click', function() {
            // Clear the input to allow selecting the same files again
            fileInput.value = '';
            fileInput.click();
        });
        
        analyzeImagesBtn.addEventListener('click', function() {
            const mode = document.querySelector('input[name="analysisMode"]:checked').value;
            if (mode === 'same') {
                analyzeMultipleProducts(capturedImages, resultElem);
            } else {
                analyzeMultipleItems(capturedImages, resultElem);
            }
            // Hide the analyze button after starting analysis
            analyzeImagesBtn.style.display = 'none';
        });
        
        doneButton.addEventListener('click', function() {
            if (window.itemsAddedCount && window.itemsAddedCount > 0) {
                alert(`Successfully added ${window.itemsAddedCount} items to inventory!`);
            }
            bsModal.hide();
            window.location.reload();
        });
        
        // Reset form when modal is hidden
        modalElem.addEventListener('hidden.bs.modal', function() {
            capturedImages = [];
            imageContainer.innerHTML = '';
            resultElem.innerHTML = '';
            addToInventoryDiv.style.display = 'none';
            imageGallery.style.display = 'none';
            analyzeImagesBtn.style.display = 'none';
            
            // Reset multi-item mode
            window.multipleItemsMode = false;
            window.itemsAddedCount = undefined;
            document.getElementById('done-button').style.display = 'none';
        });
        
        // Update form when modal is shown
        modalElem.addEventListener('shown.bs.modal', function() {
            updateFormFields('{{ active_tab }}');
        });
        
        function addImageToGallery(dataUrl, index) {
            const imgDiv = document.createElement('div');
            imgDiv.className = 'position-relative';
            imgDiv.innerHTML = `
                <img src="${dataUrl}" alt="Captured product ${index + 1}" 
                     style="width:150px; height:150px; object-fit:cover; border:1px solid #ccc; border-radius:4px;">
                <button type="button" class="btn btn-sm btn-danger position-absolute top-0 end-0" 
                        onclick="removeImage(${index})" style="margin:2px;">×</button>
            `;
            imageContainer.appendChild(imgDiv);
        }
        
        window.removeImage = function(index) {
            capturedImages.splice(index, 1);
            imageContainer.innerHTML = '';
            capturedImages.forEach((img, i) => {
                addImageToGallery(img, i);
            });
            if (capturedImages.length > 0) {
                // Show analyze button again when images are modified
                analyzeImagesBtn.style.display = 'inline-block';
                resultElem.innerHTML = '';
                addToInventoryDiv.style.display = 'none';
            } else {
                resultElem.innerHTML = '';
                addToInventoryDiv.style.display = 'none';
                analyzeImagesBtn.style.display = 'none';
            }
        }

        inventoryForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = {
                tab: document.getElementById('inventory-location').value
            };
            
            // Add dynamic fields
            const tableId = formData.tab;
            fetch(`/get_table_config/${tableId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        data.columns.forEach(col => {
                            const field = document.getElementById(`inventory-${col}`);
                            if (field) {
                                formData[col] = field.value;
                            }
                        });
                        
                        // Send to backend to add to inventory
                        return fetch('/add', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded',
                            },
                            body: new URLSearchParams(formData)
                        });
                    }
                })
                .then(response => response.text())
                .then(() => {
                    // Increment counter for multi-item mode
                    if (window.multipleItemsMode && window.itemsAddedCount !== undefined) {
                        window.itemsAddedCount++;
                        alert(`Item ${window.itemsAddedCount} added to inventory!`);
                    } else {
                        alert('Item added to inventory!');
                        bsModal.hide();
                        window.location.reload();
                    }
                    
                    // Clear form for next item
                    document.getElementById('inventory-form').reset();
                    // Reset only purchase date fields to today
                    const dateInputs = document.querySelectorAll('#inventory-form input[type="date"]');
                    dateInputs.forEach(input => {
                        const fieldId = input.id;
                        if (fieldId.toLowerCase().includes('purchase')) {
                            input.value = new Date().toISOString().split('T')[0];
                        }
                    });
                })
                .catch(error => {
                    alert('Error adding item: ' + error);
                });
        });
    });

    // Inline editing functionality for all fields
    document.addEventListener('DOMContentLoaded', function() {
        // Handle click on editable cells
        document.addEventListener('click', function(e) {
            const cell = e.target.closest('.editable-cell');
            if (cell && cell.querySelector('.editable-input').style.display === 'none') {
                const display = cell.querySelector('.editable-display');
                const input = cell.querySelector('.editable-input');
                display.style.display = 'none';
                input.style.display = 'inline-block';
                input.focus();
                input.select();
            }
        });
        // Handle input events
        document.addEventListener('input', function(e) {
            if (e.target.classList.contains('editable-input')) {
                const cell = e.target.closest('.editable-cell');
                const display = cell.querySelector('.editable-display');
                display.textContent = e.target.value;
            }
        });
        // Handle blur (save on click away)
        document.addEventListener('blur', function(e) {
            if (e.target.classList.contains('editable-input')) {
                const cell = e.target.closest('.editable-cell');
                const rowid = cell.dataset.rowid;
                const column = cell.dataset.column;
                const value = e.target.value;
                const originalValue = cell.dataset.value;
                const display = cell.querySelector('.editable-display');
                const input = cell.querySelector('.editable-input');
                display.style.display = 'inline';
                input.style.display = 'none';
                if (value !== originalValue) {
                    saveInlineEdit(rowid, column, value);
                    cell.dataset.value = value;
                }
            }
        }, true);
        // Handle Enter key (save)
        document.addEventListener('keydown', function(e) {
            if (e.target.classList.contains('editable-input') && e.key === 'Enter') {
                e.target.blur();
            }
        });
        // Handle Escape key (cancel)
        document.addEventListener('keydown', function(e) {
            if (e.target.classList.contains('editable-input') && e.key === 'Escape') {
                const cell = e.target.closest('.editable-cell');
                const display = cell.querySelector('.editable-display');
                const input = cell.querySelector('.editable-input');
                input.value = cell.dataset.value;
                display.textContent = cell.dataset.value;
                display.style.display = 'inline';
                input.style.display = 'none';
                input.blur();
            }
        });
    });
    function saveInlineEdit(rowid, column, value) {
        const formData = new FormData();
        formData.append('rowid', rowid);
        formData.append('column', column);
        formData.append('value', value);
        formData.append('tab', '{{ active_tab }}');
        fetch('/inline_edit', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Optional: show success indicator
                console.log('Value updated successfully');
            } else {
                alert('Error updating value: ' + data.error);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error updating value');
        });
    }

    function analyzeMultipleProducts(dataUrls, resultElem) {
        resultElem.innerHTML = '<div class="text-info">Analyzing products from multiple images...</div>';
        
        // Analyze each image
        const analysisPromises = dataUrls.map(dataUrl => 
            fetch('/analyze_product', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({image: dataUrl})
            }).then(response => response.json())
        );
        
        Promise.all(analysisPromises)
            .then(results => {
                // Combine results from all images
                const combinedProduct = combineProductResults(results);
                
                let html = `
                    <div class="card">
                        <div class="card-body">
                            <h6 class="card-title">Combined Product Analysis Results:</h6>
                            <p><strong>Name:</strong> ${combinedProduct.product_name}</p>
                            <p><strong>Brand:</strong> ${combinedProduct.brand}</p>
                            <p><strong>Weight:</strong> ${combinedProduct.weight}</p>
                            <p><strong>Amount:</strong> ${combinedProduct.amount}</p>
                            ${combinedProduct.expiration_date && combinedProduct.expiration_date !== 'null' ? `<p><strong>Expiration Date:</strong> ${combinedProduct.expiration_date}</p>` : ''}
                            ${combinedProduct.best_before_date && combinedProduct.best_before_date !== 'null' ? `<p><strong>Best Before Date:</strong> ${combinedProduct.best_before_date}</p>` : ''}
                            ${combinedProduct.sell_by_date && combinedProduct.sell_by_date !== 'null' ? `<p><strong>Sell By Date:</strong> ${combinedProduct.sell_by_date}</p>` : ''}
                            <p><strong>Description:</strong> ${combinedProduct.description}</p>
                        </div>
                    </div>
                `;
                resultElem.innerHTML = html;
                
                // Pre-fill the form
                const itemField = document.getElementById('inventory-item');
                const weightField = document.getElementById('inventory-weight');
                const countField = document.getElementById('inventory-count');
                
                if (itemField) itemField.value = combinedProduct.product_name;
                if (weightField) weightField.value = combinedProduct.weight;
                if (countField) countField.value = combinedProduct.amount;
                
                // Handle date fields - populate all date fields with appropriate AI-detected dates
                const dateFields = document.querySelectorAll('input[type="date"]');
                dateFields.forEach(dateField => {
                    const fieldId = dateField.id;
                    let detectedDate = null;
                    
                    // Try to match field ID with appropriate date type
                    if (fieldId.includes('expiration') || fieldId.includes('expiry')) {
                        detectedDate = combinedProduct.expiration_date;
                    } else if (fieldId.includes('best_before') || fieldId.includes('bestbefore')) {
                        detectedDate = combinedProduct.best_before_date;
                    } else if (fieldId.includes('sell_by') || fieldId.includes('sellby')) {
                        detectedDate = combinedProduct.sell_by_date;
                    } else {
                        // For generic date fields, use priority order
                        if (combinedProduct.expiration_date && combinedProduct.expiration_date !== 'null') {
                            detectedDate = combinedProduct.expiration_date;
                        } else if (combinedProduct.best_before_date && combinedProduct.best_before_date !== 'null') {
                            detectedDate = combinedProduct.best_before_date;
                        } else if (combinedProduct.sell_by_date && combinedProduct.sell_by_date !== 'null') {
                            detectedDate = combinedProduct.sell_by_date;
                        }
                    }
                    
                    if (detectedDate && detectedDate !== 'null') {
                        dateField.value = detectedDate;
                    }
                    // Don't default to today's date - leave field empty if no date detected
                });
                
                document.getElementById('add-to-inventory').style.display = 'block';
                
                // Reset multi-item mode and hide Done button
                window.multipleItemsMode = false;
                window.itemsAddedCount = undefined;
                document.getElementById('done-button').style.display = 'none';
            })
            .catch(error => {
                resultElem.innerHTML = `<div class="text-danger">Error: ${error}</div>`;
            });
    }
    
    function combineProductResults(results) {
        const validResults = results.filter(r => r.success && r.data);
        if (validResults.length === 0) {
            return {
                product_name: "Unknown Product",
                brand: "Unknown Brand",
                weight: "Unknown",
                amount: 1,
                expiration_date: null,
                best_before_date: null,
                sell_by_date: null,
                description: "No valid analysis results"
            };
        }
        
        // Combine results intelligently
        const combined = {
            product_name: "Unknown Product",
            brand: "Unknown Brand",
            weight: "Unknown",
            amount: 1,
            expiration_date: null,
            best_before_date: null,
            sell_by_date: null,
            description: ""
        };
        
        // Take the first non-unknown product name
        for (let result of validResults) {
            if (result.data.product_name && result.data.product_name !== "Unknown Product") {
                combined.product_name = result.data.product_name;
                break;
            }
        }
        
        // Take the first non-unknown brand
        for (let result of validResults) {
            if (result.data.brand && result.data.brand !== "Unknown Brand") {
                combined.brand = result.data.brand;
                break;
            }
        }
        
        // Take the first non-unknown weight
        for (let result of validResults) {
            if (result.data.weight && result.data.weight !== "Unknown") {
                combined.weight = result.data.weight;
                break;
            }
        }
        
        // Take the first non-unknown amount
        for (let result of validResults) {
            if (result.data.amount && result.data.amount !== 1) {
                combined.amount = result.data.amount;
                break;
            }
        }
        
        // Take the first valid date for each type
        for (let result of validResults) {
            if (result.data.expiration_date && result.data.expiration_date !== 'null') {
                combined.expiration_date = result.data.expiration_date;
                break;
            }
        }
        
        for (let result of validResults) {
            if (result.data.best_before_date && result.data.best_before_date !== 'null') {
                combined.best_before_date = result.data.best_before_date;
                break;
            }
        }
        
        for (let result of validResults) {
            if (result.data.sell_by_date && result.data.sell_by_date !== 'null') {
                combined.sell_by_date = result.data.sell_by_date;
                break;
            }
        }
        
        // Combine descriptions
        const descriptions = validResults
            .map(r => r.data.description)
            .filter(d => d && d !== "No description available")
            .filter((d, i, arr) => arr.indexOf(d) === i); // Remove duplicates
        
        combined.description = descriptions.length > 0 ? descriptions.join('; ') : "No description available";
        
        return combined;
    }
    
    function analyzeMultipleItems(dataUrls, resultElem) {
        resultElem.innerHTML = '<div class="text-info">Analyzing multiple items...</div>';
        
        // Analyze each image as a separate item
        const analysisPromises = dataUrls.map(dataUrl => 
            fetch('/analyze_product', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({image: dataUrl})
            }).then(response => response.json())
        );
        
        Promise.all(analysisPromises)
            .then(results => {
                const validResults = results.filter(r => r.success && r.data);
                
                if (validResults.length === 0) {
                    resultElem.innerHTML = '<div class="text-danger">No valid items found in images</div>';
                    return;
                }
                
                let html = `
                    <div class="card">
                        <div class="card-body">
                            <h6 class="card-title">Multiple Items Analysis Results:</h6>
                            <p><strong>Found ${validResults.length} item(s):</strong></p>
                `;
                
                validResults.forEach((result, index) => {
                    const product = result.data;
                    html += `
                        <div class="border rounded p-3 mb-2">
                            <h6>Item ${index + 1}:</h6>
                            <p><strong>Name:</strong> ${product.product_name}</p>
                            <p><strong>Brand:</strong> ${product.brand}</p>
                            <p><strong>Weight:</strong> ${product.weight}</p>
                            <p><strong>Amount:</strong> ${product.amount}</p>
                            ${product.expiration_date && product.expiration_date !== 'null' ? `<p><strong>Expiration Date:</strong> ${product.expiration_date}</p>` : ''}
                            ${product.best_before_date && product.best_before_date !== 'null' ? `<p><strong>Best Before Date:</strong> ${product.best_before_date}</p>` : ''}
                            ${product.sell_by_date && product.sell_by_date !== 'null' ? `<p><strong>Sell By Date:</strong> ${product.sell_by_date}</p>` : ''}
                            <p><strong>Description:</strong> ${product.description}</p>
                            <button class="btn btn-sm btn-success" onclick="addItemToInventory(${index})">Add This Item</button>
                        </div>
                    `;
                });
                
                html += `
                        </div>
                    </div>
                `;
                resultElem.innerHTML = html;
                
                // Store the results globally for the add buttons
                window.multipleItemsResults = validResults;
                
                // Set multi-item mode and show Done button
                window.multipleItemsMode = true;
                window.itemsAddedCount = 0;
                document.getElementById('done-button').style.display = 'inline-block';
            })
            .catch(error => {
                resultElem.innerHTML = `<div class="text-danger">Error: ${error}</div>`;
            });
    }
    
    window.addItemToInventory = function(index) {
        const product = window.multipleItemsResults[index].data;
        
        // Pre-fill the form with this item's data
        const itemField = document.getElementById('inventory-item');
        const weightField = document.getElementById('inventory-weight');
        const countField = document.getElementById('inventory-count');
        
        if (itemField) itemField.value = product.product_name;
        if (weightField) weightField.value = product.weight;
        if (countField) countField.value = product.amount;
        
        // Handle date fields
        const dateFields = document.querySelectorAll('input[type="date"]');
        dateFields.forEach(dateField => {
            const fieldId = dateField.id;
            let detectedDate = null;
            
            if (fieldId.includes('expiration') || fieldId.includes('expiry')) {
                detectedDate = product.expiration_date;
            } else if (fieldId.includes('best_before') || fieldId.includes('bestbefore')) {
                detectedDate = product.best_before_date;
            } else if (fieldId.includes('sell_by') || fieldId.includes('sellby')) {
                detectedDate = product.sell_by_date;
            } else {
                if (product.expiration_date && product.expiration_date !== 'null') {
                    detectedDate = product.expiration_date;
                } else if (product.best_before_date && product.best_before_date !== 'null') {
                    detectedDate = product.best_before_date;
                } else if (product.sell_by_date && product.sell_by_date !== 'null') {
                    detectedDate = product.sell_by_date;
                }
            }
            
            if (detectedDate && detectedDate !== 'null') {
                dateField.value = detectedDate;
            }
            // Don't default to today's date - leave field empty if no date detected
        });
        
        document.getElementById('add-to-inventory').style.display = 'block';
    }
</script>
</body>
</html>
'''

SETTINGS_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Settings - Food Inventory Management</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body class="bg-light">
<div class="container py-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h1>Settings</h1>
        <a href="{{ url_for('index') }}" class="btn btn-outline-secondary">Back to Inventory</a>
    </div>
    
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="alert alert-info">{{ messages[0] }}</div>
      {% endif %}
    {% endwith %}
    
    <!-- Add New Table -->
    <div class="card mb-4">
        <div class="card-header">
            <h5 class="mb-0">Add New Table</h5>
        </div>
        <div class="card-body">
            <form method="post" action="{{ url_for('add_table') }}">
                <div class="row">
                    <div class="col-md-3">
                        <label class="form-label">Table ID:</label>
                        <input type="text" name="table_id" class="form-control" required placeholder="e.g., fridge">
                    </div>
                    <div class="col-md-3">
                        <label class="form-label">Table Name:</label>
                        <input type="text" name="table_name" class="form-control" required placeholder="e.g., Refrigerator">
                    </div>
                    <div class="col-md-6">
                        <label class="form-label">Display Names (comma-separated):</label>
                        <input type="text" name="display_columns" class="form-control" required placeholder="e.g., Item,Date of Purchase,Expiration Date,Amount">
                        <small class="form-text text-muted">Column names will be automatically generated (lowercase, spaces become underscores)</small>
                    </div>
                </div>
                <button type="submit" class="btn btn-success mt-3">Add Table</button>
            </form>
        </div>
    </div>
    
    <!-- Existing Tables -->
    <div class="card">
        <div class="card-header">
            <h5 class="mb-0">Manage Tables</h5>
        </div>
        <div class="card-body">
            {% for table_id, table_config in tables.items() %}
            <div class="border rounded p-3 mb-3">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="flex-grow-1">
                        <h6>{{ table_config.name }} ({{ table_id }})</h6>
                        <p class="text-muted mb-2">
                            <strong>Display Names:</strong> {{ table_config.display_columns|join(', ') }}<br>
                            <strong>Column Names:</strong> <small>{{ table_config.columns|join(', ') }}</small>
                        </p>
                    </div>
                    <div class="btn-group">
                        <button class="btn btn-sm btn-primary" onclick="editTable('{{ table_id }}')">Edit</button>
                        <a href="{{ url_for('delete_table_route', table_id=table_id) }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete this table and all its data?')">Delete</a>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
</div>

<!-- Edit Table Modal -->
<div class="modal fade" id="editTableModal" tabindex="-1">
    <div class="modal-dialog modal-lg">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">Edit Table</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <form id="editTableForm" method="post">
                    <input type="hidden" id="edit-table-id" name="table_id">
                    <div class="mb-3">
                        <label class="form-label">Table Name:</label>
                        <input type="text" id="edit-table-name" name="table_name" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Display Names (comma-separated):</label>
                        <input type="text" id="edit-display-columns" name="display_columns" class="form-control" required>
                        <small class="form-text text-muted">Column names will be automatically generated (lowercase, spaces become underscores)</small>
                    </div>
                </form>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                <button type="submit" form="editTableForm" class="btn btn-primary">Save Changes</button>
            </div>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
function editTable(tableId) {
    // Fetch table configuration
    fetch(`/get_table_config/${tableId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                document.getElementById('edit-table-id').value = tableId;
                document.getElementById('edit-table-name').value = data.name;
                document.getElementById('edit-display-columns').value = data.display_columns.join(',');
                
                // Set form action
                document.getElementById('editTableForm').action = '/edit_table';
                
                // Show modal
                new bootstrap.Modal(document.getElementById('editTableModal')).show();
            }
        });
}
</script>
</body>
</html>
'''

FORM_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ title }}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body class="bg-light">
<div class="container py-4">
    <h2>{{ title }}</h2>
    <form method="post">
        {% for col in columns %}
        <div class="mb-3">
            <label class="form-label">{{ display_columns[loop.index0] }}</label>
            {% if col == 'amount' or col == 'count' %}
            <input type="number" name="{{ col }}" class="form-control" value="{{ values.get(col, '') }}" min="0" step="1" required>
            {% elif 'date' in col.lower() %}
            <input type="date" name="{{ col }}" class="form-control" value="{{ values.get(col, '') }}" required>
            {% else %}
            <input type="text" name="{{ col }}" class="form-control" value="{{ values.get(col, '') }}" required>
            {% endif %}
        </div>
        {% endfor %}
        <button type="submit" class="btn btn-primary">Save</button>
        <a href="{{ url_for('index', tab=active_tab) }}" class="btn btn-secondary">Cancel</a>
    </form>
</div>
</body>
</html>
'''

# Anthropic AI endpoint
@app.route('/analyze_product', methods=['POST'])
def analyze_product():
    try:
        # Get image data from request
        data = request.get_json()
        image_data = data.get('image')
        
        # Remove data URL prefix
        if image_data.startswith('data:image'):
            image_data = image_data.split(',')[1]
        
        # Decode base64 image
        image_bytes = base64.b64decode(image_data)
        
        # Prepare prompt for Anthropic
        prompt = """Analyze this product image and extract the following information in JSON format:
        {
            "product_name": "simple product name without adjectives or brand (e.g., 'Chicken Breast', 'Pasta', 'Milk')",
            "brand": "brand name if visible",
            "weight": "weight/volume (e.g., '16 oz', '500g', '1 lb')",
            "amount": "quantity if multiple items (e.g., 1, 2, 6)",
            "expiration_date": "expiration date if visible (format: YYYY-MM-DD, e.g., '2024-12-31')",
            "best_before_date": "best before date if visible (format: YYYY-MM-DD, e.g., '2024-12-31')",
            "sell_by_date": "sell by date if visible (format: YYYY-MM-DD, e.g., '2024-12-31')",
            "description": "brief description of the product"
        }
        
        For product_name: Use only the core product type, no adjectives like 'premium', 'organic', 'fresh', etc. No brand names in the product_name field.
        For dates: Look carefully for any expiration, best before, sell by, or use by dates on the package. If found, use YYYY-MM-DD format. If no date is visible, set to null.
        Focus on food products. If weight/amount information is not clearly visible, estimate based on typical packaging sizes. Return only valid JSON."""
        
        # Call Anthropic API
        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        payload = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_data
                            }
                        }
                    ]
                }
            ]
        }
        
        response = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload)
        
        if response.status_code != 200:
            return jsonify({"success": False, "error": f"API Error {response.status_code}: {response.text}"}), 500
        
        # Parse Anthropic response
        ai_response = response.json()
        content = ai_response['content'][0]['text']
        
        # Try to extract JSON from the response
        try:
            start = content.find('{')
            end = content.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = content[start:end]
                product_data = json.loads(json_str)
            else:
                product_data = {
                    "product_name": "Unknown Product",
                    "brand": "Unknown Brand",
                    "weight": "Unknown",
                    "amount": 1,
                    "expiration_date": None,
                    "best_before_date": None,
                    "sell_by_date": None,
                    "description": content
                }
        except json.JSONDecodeError:
            product_data = {
                "product_name": "Unknown Product",
                "brand": "Unknown Brand",
                "weight": "Unknown",
                "amount": 1,
                "expiration_date": None,
                "best_before_date": None,
                "sell_by_date": None,
                "description": content
            }
        
        return jsonify({"success": True, "data": product_data})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/get_table_config/<table_id>')
def get_table_config(table_id):
    """Get table configuration for dynamic form generation"""
    try:
        tables = get_tables_config()
        if table_id in tables:
            return jsonify({
                "success": True,
                "name": tables[table_id]['name'],
                "columns": tables[table_id]['columns'],
                "display_columns": tables[table_id]['display_columns']
            })
        else:
            return jsonify({"success": False, "error": "Table not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/settings')
def settings():
    """Settings page for managing tables"""
    tables = get_tables_config()
    return render_template_string(SETTINGS_TEMPLATE, tables=tables)

@app.route('/add_table', methods=['POST'])
def add_table():
    """Add a new table"""
    try:
        table_id = request.form.get('table_id', '').strip()
        table_name = request.form.get('table_name', '').strip()
        display_columns_str = request.form.get('display_columns', '')
        
        if not table_id or not table_name or not display_columns_str:
            flash('All fields are required!')
            return redirect(url_for('settings'))
        
        # Convert display names to column names (replace spaces with underscores, lowercase)
        display_columns = [col.strip() for col in display_columns_str.split(',')]
        columns = []
        for display_col in display_columns:
            col_name = display_col.lower()
            col_name = col_name.replace(' ', '_').replace('-', '_').replace('&', '_').replace('(', '_').replace(')', '_').replace('$', '').replace('/', '_')
            col_name = ''.join(c for c in col_name if c.isalnum() or c == '_')
            while '__' in col_name:
                col_name = col_name.replace('__', '_')
            col_name = col_name.strip('_')
            columns.append(col_name)
        
        if len(columns) != len(display_columns):
            flash('Number of columns and display names must match!')
            return redirect(url_for('settings'))
        
        create_table(table_id, table_name, columns, display_columns)
        flash(f'Table "{table_name}" created successfully!')
        
    except Exception as e:
        flash(f'Error creating table: {str(e)}')
    
    return redirect(url_for('settings'))

@app.route('/edit_table', methods=['POST'])
def edit_table():
    """Edit an existing table"""
    try:
        table_id = request.form.get('table_id', '').strip()
        table_name = request.form.get('table_name', '').strip()
        display_columns_str = request.form.get('display_columns', '')
        
        if not table_id or not table_name or not display_columns_str:
            flash('All fields are required!')
            return redirect(url_for('settings'))
        
        # Convert display names to column names (replace spaces with underscores, lowercase)
        display_columns = [col.strip() for col in display_columns_str.split(',')]
        columns = []
        for display_col in display_columns:
            col_name = display_col.lower()
            col_name = col_name.replace(' ', '_').replace('-', '_').replace('&', '_').replace('(', '_').replace(')', '_').replace('$', '').replace('/', '_')
            col_name = ''.join(c for c in col_name if c.isalnum() or c == '_')
            while '__' in col_name:
                col_name = col_name.replace('__', '_')
            col_name = col_name.strip('_')
            columns.append(col_name)
        
        if len(columns) != len(display_columns):
            flash('Number of columns and display names must match!')
            return redirect(url_for('settings'))
        
        update_table(table_id, table_name, columns, display_columns)
        flash(f'Table "{table_name}" updated successfully!')
        
    except Exception as e:
        flash(f'Error updating table: {str(e)}')
    
    return redirect(url_for('settings'))

@app.route('/delete_table/<table_id>')
def delete_table_route(table_id):
    """Delete a table"""
    try:
        tables = get_tables_config()
        if table_id in tables:
            table_name = tables[table_id]['name']
            delete_table(table_id)
            flash(f'Table "{table_name}" deleted successfully!')
        else:
            flash('Table not found!')
    except Exception as e:
        flash(f'Error deleting table: {str(e)}')
    
    return redirect(url_for('settings'))

@app.route('/update_table_order', methods=['POST'])
def update_table_order_route():
    try:
        data = request.get_json()
        table_orders = data.get('table_orders', {})
        
        if table_orders:
            update_table_order(table_orders)
            return jsonify({'success': True, 'message': 'Tab order updated successfully!'})
        else:
            return jsonify({'success': False, 'error': 'No table orders provided'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/')
def index():
    tab = request.args.get('tab', 'pantry')
    tables = get_tables_config()
    
    if tab not in tables:
        tab = list(tables.keys())[0] if tables else 'pantry'
    
    search = request.args.get('search', '').strip()
    order = request.args.get('order', 'desc')
    
    table_config = tables[tab]
    table_name = tab
    columns = table_config['columns']
    display_columns = table_config['display_columns']
    
    conn = get_db_connection()
    cur = conn.cursor()
    query = f'SELECT rowid, * FROM {table_name}'
    params = []
    if search:
        # Search in any text column (not just 'item')
        search_conditions = []
        for col in columns:
            if col != 'rowid':  # Don't search in rowid
                search_conditions.append(f'[{col}] LIKE ?')
                params.append(f'%{search}%')
        if search_conditions:
            query += ' WHERE ' + ' OR '.join(search_conditions)
    if order not in ['asc', 'desc']:
        order = 'desc'
    
    # Find a date column for ordering (prefer dateofpurchase, then any column with 'date' in the name)
    date_column = None
    for col in columns:
        if col == 'dateofpurchase' or 'date' in col.lower():
            date_column = col
            break
    
    if date_column:
        query += f' ORDER BY [{date_column}] {order.upper()}'
    else:
        query += f' ORDER BY rowid {order.upper()}'
    
    cur.execute(query, params)
    items = cur.fetchall()
    conn.close()
    
    # Format date columns for display
    formatted_items = []
    for row in items:
        row_dict = dict(row)
        # Format any date columns
        for col in columns:
            if col == 'dateofpurchase' or 'date' in col.lower():
                if row_dict.get(col):
                    try:
                        row_dict[col] = datetime.strptime(row_dict[col], '%Y-%m-%d').strftime('%m/%d/%Y')
                    except Exception:
                        pass
        formatted_items.append(row_dict)
    
    return render_template_string(TEMPLATE, 
                                items=formatted_items, 
                                columns=columns,
                                display_columns=display_columns,
                                tables=tables,
                                active_tab=tab)

@app.route('/add', methods=['GET', 'POST'])
def add_item():
    tab = request.args.get('tab') or request.form.get('tab', 'pantry')
    tables = get_tables_config()
    
    if tab not in tables:
        tab = list(tables.keys())[0] if tables else 'pantry'
    
    table_config = tables[tab]
    table_name = tab
    columns = table_config['columns']
    display_columns = table_config['display_columns']
    
    if request.method == 'POST':
        values = [request.form.get(col, '') for col in columns]
        conn = get_db_connection()
        cur = conn.cursor()
        placeholders = ', '.join(['?'] * len(columns))
        # Escape column names with square brackets
        escaped_columns = [f'[{col}]' for col in columns]
        cur.execute(f'INSERT INTO {table_name} ({', '.join(escaped_columns)}) VALUES ({placeholders})', values)
        conn.commit()
        conn.close()
        flash('Item added!')
        return redirect(url_for('index', tab=tab))
    
    return render_template_string(FORM_TEMPLATE, 
                                title=f'Add Item to {table_config["name"]}', 
                                columns=columns,
                                display_columns=display_columns,
                                values={},
                                active_tab=tab)

@app.route('/edit/<int:rowid>', methods=['GET', 'POST'])
def edit_item(rowid):
    tab = request.args.get('tab', 'pantry')
    tables = get_tables_config()
    
    if tab not in tables:
        tab = list(tables.keys())[0] if tables else 'pantry'
    
    table_config = tables[tab]
    table_name = tab
    columns = table_config['columns']
    display_columns = table_config['display_columns']
    
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == 'POST':
        values = [request.form.get(col, '') for col in columns]
        # Escape column names with square brackets
        set_clause = ', '.join([f'[{col}]=?' for col in columns])
        cur.execute(f'UPDATE {table_name} SET {set_clause} WHERE rowid=?', (*values, rowid))
        conn.commit()
        conn.close()
        flash('Item updated!')
        return redirect(url_for('index', tab=tab))
    
    cur.execute(f'SELECT rowid, * FROM {table_name} WHERE rowid=?', (rowid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        flash('Item not found!')
        return redirect(url_for('index', tab=tab))
    
    values = {col: row[col] for col in columns}
    return render_template_string(FORM_TEMPLATE, 
                                title=f'Edit Item in {table_config["name"]}', 
                                columns=columns,
                                display_columns=display_columns,
                                values=values,
                                active_tab=tab)

@app.route('/delete/<int:rowid>')
def delete_item(rowid):
    tab = request.args.get('tab', 'pantry')
    tables = get_tables_config()
    
    if tab not in tables:
        tab = list(tables.keys())[0] if tables else 'pantry'
    
    table_name = tab
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f'DELETE FROM {table_name} WHERE rowid=?', (rowid,))
    conn.commit()
    conn.close()
    flash('Item deleted!')
    return redirect(url_for('index', tab=tab))

@app.route('/inline_edit', methods=['POST'])
def inline_edit():
    try:
        tab = request.form.get('tab')
        rowid = request.form.get('rowid')
        column = request.form.get('column')
        value = request.form.get('value')
        if not tab or not rowid or not column:
            return jsonify({'success': False, 'error': 'Missing parameters'})
        tables = get_tables_config()
        if tab not in tables:
            return jsonify({'success': False, 'error': 'Invalid table'})
        if column not in tables[tab]['columns']:
            return jsonify({'success': False, 'error': 'Invalid column'})
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f'UPDATE {tab} SET [{column}]=? WHERE rowid=?', (value, rowid))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        print(f'Test database not found at {DB_PATH}')
    else:
        app.run(debug=True, host='0.0.0.0', port=5000) 