chrome.runtime.onInstalled.addListener(() => chrome.contextMenus.create({ id: 'olmavax-ask', title: 'Ask Olmavax about "%s"', contexts: ['selection'] }));
chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === 'olmavax-ask') { chrome.storage.local.set({ pending: info.selectionText }); chrome.action.setBadgeText({ text: '1' }); }
});