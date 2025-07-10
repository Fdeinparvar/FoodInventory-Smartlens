# Food Inventory Management System - V3

A comprehensive, feature-rich web application for managing food inventory across multiple locations with AI-powered product analysis, dynamic table management, and modern UI features.

## 🚀 Key Features

### 📱 Smart Lens AI Analysis
- **Multi-image capture**: Take multiple photos of the same item or different items
- **AI-powered product recognition**: Automatically extracts product information from images
- **Intelligent data extraction**: Detects item names, amounts, expiration dates, and more
- **Flexible analysis modes**: 
  - Same Item (Multiple Angles): Combine multiple photos for better analysis
  - Multiple Items: Analyze different products in separate photos
- **Dynamic form generation**: Automatically adapts to each location's specific fields

### 🗂️ Dynamic Table Management
- **Multiple inventory locations**: Create unlimited custom locations (pantry, freezer, fridge, etc.)
- **Custom column structure**: Define your own fields for each location
- **Drag-and-drop tab reordering**: Easily rearrange your inventory locations
- **Real-time table editing**: Add, edit, or delete tables through the web interface
- **Automatic schema management**: Database structure updates automatically when you modify tables

### ✏️ Inline Editing
- **Click-to-edit**: Click any cell to edit it directly in the table
- **Smart input types**: 
  - Number inputs for amounts and counts
  - Date pickers for date fields
  - Text inputs for names and descriptions
- **Visual feedback**: Hover effects and visual cues for editable cells
- **Auto-save**: Changes save automatically when you click away or press Enter
- **Keyboard shortcuts**: Arrow keys, Enter, and Escape support

### 🔍 Advanced Search & Organization
- **Multi-column search**: Search across all text fields, not just item names
- **Smart date ordering**: Automatically orders by date fields when available
- **Flexible sorting**: Newest first or oldest first options
- **Real-time filtering**: Instant search results as you type

### 🎨 Modern UI/UX
- **Responsive design**: Works perfectly on desktop, tablet, and mobile
- **Bootstrap 5**: Modern, clean interface with professional styling
- **Visual feedback**: Hover effects, loading states, and success messages
- **Accessible design**: Keyboard navigation and screen reader support

## 📋 System Requirements

- **Python**: 3.7 or higher
- **Dependencies**: Flask, requests, sqlite3 (included with Python)
- **Storage**: SQLite database (automatically created)
- **Network**: Optional - can run locally or on your network

## 🛠️ Installation & Setup

### 1. Install Dependencies
```bash
pip install flask requests
```

### 2. Configure API Key (Optional)
For AI analysis features, you'll need an Anthropic API key:
- Create a `config.py` file in the v3 directory
- Add: `ANTHROPIC_API_KEY = "your-api-key-here"`
- Or set environment variable: `ANTHROPIC_API_KEY`

### 3. Run the Application
```bash
cd //Path of folder//
python food_webapp_V3.py
```

### 4. Access the Application
- **Local**: http://127.0.0.1:5000/
- **Network**: http://your-ip-address:5000/

## 📖 User Guide

### Getting Started

1. **First Launch**: The app automatically creates default tables (Pantry, Basement Freezer)
2. **Default Tab**: Pantry is automatically set as the first tab
3. **Database Location**: Database is created in the same directory as the script

### Managing Inventory Locations

#### Adding New Locations
1. Click "Settings" in the top-right corner
2. Fill out the "Add New Table" form:
   - **Table ID**: Unique identifier (e.g., `fridge`, `garage_freezer`)
   - **Table Name**: Display name (e.g., `Refrigerator`, `Garage Freezer`)
   - **Columns**: Comma-separated field names (e.g., `item,dateofpurchase,amount,expiry_date`)
   - **Display Names**: Comma-separated labels (e.g., `Item,Date of Purchase,Amount,Expiry Date`)
3. Click "Add Table"

#### Reordering Tabs
- **Drag and drop**: Click and drag any tab to reorder it
- **Visual feedback**: Tabs show blue border during drag operations
- **Auto-save**: Order is automatically saved to database

#### Editing Locations
1. Go to Settings page
2. Click "Edit" next to any table
3. Modify name, columns, or display names
4. Click "Save Changes"

### Using Smart Lens AI Analysis

#### Single Item Analysis
1. Select "Same Item (Multiple Angles)" mode
2. Click "Smart Lens" button
3. Take multiple photos of the same product from different angles
4. Click "Analyze Images"
5. Review AI-extracted information
6. Fill in any missing fields
7. Click "Add to Inventory"

#### Multiple Items Analysis
1. Select "Multiple Items" mode
2. Click "Smart Lens" button
3. Take photos of different products
4. Click "Analyze Images"
5. For each detected item:
   - Review AI-extracted information
   - Fill in missing fields
   - Click "Add to Inventory"
6. Click "Done" when finished

#### AI Analysis Features
- **Automatic field detection**: AI identifies item names, amounts, dates
- **Expiration date detection**: Finds expiration, best before, and sell by dates
- **Amount assignment**: AI-detected amounts are assigned to the "count" field
- **Location locking**: Location is locked to current tab during analysis
- **Dynamic forms**: Form fields adapt to each location's structure

### Managing Inventory Items

#### Adding Items Manually
1. Navigate to the desired location tab
2. Click "Add New Item"
3. Fill in the required fields
4. Click "Add Item"

#### Inline Editing
- **Click any cell** to edit it directly
- **Number fields**: Use arrow keys or type numbers
- **Date fields**: Use calendar picker
- **Text fields**: Type directly
- **Save**: Press Enter or click away
- **Cancel**: Press Escape

#### Searching and Filtering
- **Search box**: Type to search across all text fields
- **Sort options**: Choose "Newest First" or "Oldest First"
- **Real-time results**: See results as you type

#### Editing and Deleting
- **Edit**: Click "Edit" button for full form editing
- **Delete**: Click "Delete" button (with confirmation)
- **Inline**: Click any cell for quick editing

## 🔧 Technical Features

### Database Management
- **SQLite database**: Lightweight, file-based storage
- **Automatic migrations**: Handles schema changes automatically
- **Data preservation**: Maintains data during table structure changes
- **Column escaping**: Handles SQL keywords in column names

### Dynamic Form Generation
- **Automatic field types**: 
  - Number inputs for amount/count fields
  - Date inputs for date fields
  - Text inputs for other fields
- **Required field detection**: Item fields are automatically required
- **Default values**: Purchase dates default to today
- **Real-time updates**: Forms update when location changes

### AI Integration
- **Anthropic Claude API**: Advanced AI analysis
- **Image processing**: Handles multiple image formats
- **Error handling**: Graceful fallbacks when AI is unavailable
- **Rate limiting**: Built-in API usage management

### Security Features
- **Input validation**: All user inputs are validated
- **SQL injection protection**: Parameterized queries
- **XSS protection**: Output escaping
- **Local network only**: Designed for personal use

## 🗄️ Database Schema

### table_settings Table
```sql
CREATE TABLE table_settings (
    table_id TEXT PRIMARY KEY,
    table_name TEXT NOT NULL,
    columns TEXT NOT NULL,           -- JSON array of column names
    display_columns TEXT NOT NULL,   -- JSON array of display names
    display_order INTEGER DEFAULT 0, -- Tab ordering
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Dynamic Tables
Each location creates its own table with the structure defined in table_settings.

## 🐛 Troubleshooting

### Common Issues

#### Database Issues
- **"Database not found"**: Check file permissions in the v3 directory
- **"Table not found"**: Go to Settings and verify table exists
- **"Column not found"**: The system handles this automatically now

#### AI Analysis Issues
- **"API key not found"**: Set up your Anthropic API key in config.py
- **"Analysis failed"**: Check internet connection and API key validity
- **"No images detected"**: Ensure photos are clear and well-lit

#### UI Issues
- **"Tabs not reordering"**: Refresh the page and try again
- **"Inline editing not working"**: Check JavaScript is enabled
- **"Form fields missing"**: Go to Settings and verify table structure

### Reset Options

#### Reset Database
1. Stop the application
2. Delete `food.db` file from v3 directory
3. Restart application

#### Reset Table Order
1. Go to Settings
2. Delete and recreate tables in desired order

## 🚀 Performance Tips

- **Large inventories**: Use search to find items quickly
- **Multiple locations**: Use tab reordering to prioritize frequently used locations
- **AI analysis**: Take clear, well-lit photos for best results
- **Network access**: Use your computer's IP address for mobile access

## 🔮 Future Enhancements

Potential improvements for future versions:
- **Export/import**: CSV/Excel export and import
- **Notifications**: Expiration date alerts
- **Recipe integration**: Link items to recipes
- **Shopping lists**: Generate shopping lists from inventory
- **Analytics**: Usage statistics and trends
- **Backup/restore**: Database backup functionality
- **Multi-user support**: User accounts and permissions

## 📝 Version History

### V3.0 - Current Version
- ✅ Smart Lens AI analysis with multi-image support
- ✅ Dynamic table management with drag-and-drop reordering
- ✅ Inline editing for all fields
- ✅ Modern Bootstrap 5 UI
- ✅ Comprehensive settings system
- ✅ Automatic database migrations
- ✅ Enhanced search and filtering
- ✅ Mobile-responsive design

### Previous Versions
- **V2**: Basic inventory management with static tables
- **V1**: Simple list-based inventory system

## 📄 License

MIT License - Free for personal and commercial use.

## 🤝 Contributing

This is a personal project, but suggestions and feedback are welcome!

---

**Note**: This application is designed for personal/local use. Do not expose it to the public internet without proper security measures. 
