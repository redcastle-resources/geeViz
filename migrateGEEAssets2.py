import ee,os,json
ee.Initialize()
###################################################################################################
# This script recursively migrates Google Earth Engine assets from one repository to a new one, sets permissions, and deletes old assets if needed.
# **Important** for this to work you need the following:
#       - The credential you're using must have editor permissions in both the source and destination repositories
#                               OR
#       - The credential you're using must have editor permissions in the destination repository, and you are willing to
#           change the permissions of all the original assets to "Anyone Can Read" (to do this, set changePermissions = True below)
#       - The geeViz package installed in your python instance. (https://github.com/gee-community/geeViz)

#Written by:
#Ian Housman ian.housman@usda.gov ian.housman@gmail.com 
#Leah Campbell leah.campbell@usda.gov leahs.campbell@gmail.com
#RedCastle Resources Inc.
#MIT License
###################################################################################################
# Repository you are moving from:
sourceRoot = 'projects/USFS/LCMS-NFS/R1/FNF'

# Repository you are moving to:
# It is assumed this folder already exists and user account has write access to it
destinationRoot = 'projects/lcms-292214/assets/migrationTest/FNF'

# If the credential you're using does not have editor permissions in the source repository
changePermissions = True
readers = []
writers = []
all_users_can_read = True
###################################################################################################
#Function to get all folders, imageCollections, images, and tables under a given folder or imageCollection level
def getTree(fromRoot,toRoot,treeList = []):
    pathPrefix = 'projects/earthengine-legacy/assets/'

    #Clean up the given paths
    if(fromRoot[-1] != '/'):fromRoot += '/'
    if(toRoot[-1] != '/'):toRoot += '/'
    fromRoot = fromRoot.replace(pathPrefix,'')
    toRoot = toRoot.replace(pathPrefix,'')
   
    #List assets - handle inconsistencies with the earthengine-legacy prefix
    try:
        assets = ee.data.listAssets({'parent':pathPrefix+fromRoot})['assets']
    except:
        assets = ee.data.listAssets({'parent':fromRoot})['assets']

    #Reursively walk down the tree
    nextLevels = []
    for asset in assets:
        fromID = asset['id']
        fromType = asset['type']
        fromID = fromID.replace('projects/earthengine-legacy/assets/','')
        toID = fromID.replace(fromRoot,toRoot)
        
        if fromType in ['FOLDER','IMAGE_COLLECTION']:
            nextLevels.append([fromID,toID])
        treeList.append([fromType,fromID,toID])  
    
    
    for i1,i2 in nextLevels:
        getTree(i1,i2,treeList)
    return treeList
###################################################################################################
#Function to copy all folders, imageCollections, images, and tables under a given folder or imageCollection level
#Permissions can also be set here 
def copyAssetTree(fromRoot,toRoot,changePermissions = False,readers = [],writers = [],all_users_can_read = True):
    treeList = getTree(fromRoot,toRoot)
    #Iterate across all assets and copy and create when appropriate
    for fromType,fromID,toID in treeList:
        if fromType in ['FOLDER','IMAGE_COLLECTION']:
            try:
                print('Creating {}: {}'.format(fromType,toID))
                ee.data.createAsset({'type':fromType, 'name': toID})

                if changePermissions:
                    print('Changing permissions for: {}'.format(toID))
                    ee.data.setAssetAcl(toID, json.dumps({u'writers': writers, u'all_users_can_read': all_users_can_read, u'readers': readers}))
            except Exception as e:
                print(e)
        else:
            try:
                print('Copying {}: {}'.format(fromType,toID))
                ee.data.copyAsset(fromID,toID,False)

                if changePermissions and fromType != 'IMAGE_COLLECTION':
                    print('Changing permissions for: {}'.format(toID))
                    ee.data.setAssetAcl(toID, json.dumps({u'writers': writers, u'all_users_can_read': all_users_can_read, u'readers': readers}))
            except Exception as e:
                print(e)
###################################################################################################
#Function to delete all folders, imageCollections, images, and tables under a given folder or imageCollection level
def deleteAssetTree(root):
    answer = input('Are you sure you want to delete all assets under {}? (y = yes, n = no) '.format(root))
    print(answer)
    if answer.lower() == 'y':
        answer = input('You answered yes. Just double checking. Are you sure you want to delete all assets under {}? (y = yes, n = no) '.format(root))
        if answer.lower() == 'y':
            treeList = getTree(root,root)
            treeList.reverse()
            for fromType, ID1,ID2 in treeList:
                print('Deleting {}'.format(ID1))
                try:
                    ee.data.deleteAsset(ID1)
                except Exception as e:
                    print(e)
###################################################################################################
#Use this function to copy assets
# copyAssetTree(sourceRoot,destinationRoot,changePermissions,readers,writers,all_users_can_read)
###################################################################################################
#!!!!!!! DANGER !!!!!!!!!
#!!!!!!! DANGER !!!!!!!!!
#!!!!!!! DANGER !!!!!!!!!
#!!!!!!! DANGER !!!!!!!!!
#Once all assets are copied and inspected, you can use this method to delete all files under the root level
#This method is final and there is no way to undo this
#deleteAssetTree(sourceRoot)