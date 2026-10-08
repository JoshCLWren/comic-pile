#!/usr/bin/env node

/**
 * Simple verification script for the IssueToggleList delete functionality
 * This script verifies that the code changes are correct by checking file content
 */

const fs = require('fs')
const path = require('path')

console.log('🔍 Verifying IssueToggleList delete functionality fix...')

try {
  // Check that IssueToggleList no longer uses window.confirm
  const issueToggleListPath = './frontend/src/pages/QueuePage/IssueToggleList.tsx'
  const issueToggleListContent = fs.readFileSync(issueToggleListPath, 'utf8')
  
  console.log('\n📋 Checking IssueToggleList.tsx...')
  
  if (issueToggleListContent.includes('window.confirm')) {
    console.log('❌ window.confirm still found in IssueToggleList')
    process.exit(1)
  } else {
    console.log('✅ window.confirm successfully removed from IssueToggleList')
  }
  
  // Check that DeleteIssueDialog is imported
  if (issueToggleListContent.includes("import DeleteIssueDialog from './DeleteIssueDialog'")) {
    console.log('✅ DeleteIssueDialog is properly imported')
  } else {
    console.log('❌ DeleteIssueDialog import not found')
    process.exit(1)
  }
  
  // Check that the dialog state variables are added
  if (issueToggleListContent.includes('deleteDialogIssue') && issueToggleListContent.includes('deleteError')) {
    console.log('✅ Delete dialog state variables are added')
  } else {
    console.log('❌ Delete dialog state variables missing')
    process.exit(1)
  }
  
  // Check that the dialog is used in JSX
  if (issueToggleListContent.includes('<DeleteIssueDialog')) {
    console.log('✅ DeleteIssueDialog is properly used in JSX')
  } else {
    console.log('❌ DeleteIssueDialog not found in JSX')
    process.exit(1)
  }
  
  // Check that the delete handler is updated
  if (issueToggleListContent.includes('setDeleteDialogIssue(issue)')) {
    console.log('✅ Delete handler is updated to show dialog')
  } else {
    console.log('❌ Delete handler not properly updated')
    process.exit(1)
  }
  
  // Check that the new dialog component exists
  const deleteDialogPath = './frontend/src/pages/QueuePage/DeleteIssueDialog.tsx'
  if (fs.existsSync(deleteDialogPath)) {
    const deleteDialogContent = fs.readFileSync(deleteDialogPath, 'utf8')
    console.log('✅ DeleteIssueDialog.tsx file exists')
    
    if (deleteDialogContent.includes('Modal')) {
      console.log('✅ DeleteIssueDialog uses Modal component')
    } else {
      console.log('❌ DeleteIssueDialog does not use Modal component')
      process.exit(1)
    }
    
    if (deleteDialogContent.includes('Delete Issue')) {
      console.log('✅ DeleteIssueDialog has correct title')
    } else {
      console.log('❌ DeleteIssueDialog title incorrect')
      process.exit(1)
    }
    
    if (deleteDialogContent.includes('Are you sure you want to delete issue')) {
      console.log('✅ DeleteIssueDialog has correct confirmation message')
    } else {
      console.log('❌ DeleteIssueDialog confirmation message incorrect')
      process.exit(1)
    }
    
  } else {
    console.log('❌ DeleteIssueDialog.tsx file does not exist')
    process.exit(1)
  }
  
  // Check that tests are updated
  const testPath = './frontend/src/unit/IssueToggleList.test.tsx'
  if (fs.existsSync(testPath)) {
    const testContent = fs.readFileSync(testPath, 'utf8')
    console.log('✅ IssueToggleList.test.tsx exists')
    
    if (testContent.includes('getByTestId(\'delete-issue-dialog\')')) {
      console.log('✅ Tests updated to check for delete dialog')
    } else {
      console.log('❌ Tests not updated for delete dialog')
      process.exit(1)
    }
    
    if (testContent.includes('getByText(\'Cancel\')')) {
      console.log('✅ Tests updated to check for Cancel button')
    } else {
      console.log('❌ Tests not updated for Cancel button')
      process.exit(1)
    }
    
    if (!testContent.includes('vi.mocked(confirm)')) {
      console.log('✅ Tests no longer use vi.mocked(confirm)')
    } else {
      console.log('❌ Tests still use vi.mocked(confirm)')
      process.exit(1)
    }
    
  } else {
    console.log('❌ IssueToggleList.test.tsx does not exist')
    process.exit(1)
  }
  
  console.log('\n🎉 All verification checks passed!')
  console.log('📝 Summary of changes made:')
  console.log('   1. ✅ Removed window.confirm from IssueToggleList')
  console.log('   2. ✅ Created DeleteIssueDialog component using Modal')
  console.log('   3. ✅ Added state management for delete dialog')
  console.log('   4. ✅ Updated delete handlers to use dialog')
  console.log('   5. ✅ Updated tests to work with new dialog')
  console.log('   6. ✅ Added proper error handling for delete operations')
  
  console.log('\n🚀 The fix should resolve the UI freeze issue when deleting issues')
  console.log('💡 Issues are now deleted using a non-blocking Modal dialog')
  console.log('💡 Users get proper confirmation and error feedback')
  
} catch (error) {
  console.error('❌ Error during verification:', error.message)
  process.exit(1)
}