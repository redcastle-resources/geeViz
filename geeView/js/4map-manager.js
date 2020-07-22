//Wrapper for mapping functions
///////////////////////////////////////////////////////////////////
//Set up some globals
var mapDiv = document.getElementById('map');

tableConverter = function(dataTableT){

  // var x = [dataTableT[0]]
  // x[0][0] = 'Year'
  // dataTableT.slice(1).map(function(i){
    
  //   i[0] = (i[0].getYear()+1900).toString()
  //   x.push(i)
  // })
  // dataTableT   = x
var lcDict = {
  '0': 'No data',
'1': 'Barren',
'2': 'Grass/forb/herb',
'3': 'Impervious',
'4': 'Shrubs',
'5': 'Snow/ice',
'6': 'Trees',
'7': 'Water'
};

var luDict = {
  '0': 'No data',
'1': 'Agriculture',
'2': 'Developed',
'3': 'Forest',
'4': 'Non-forest wetland',
'5': 'Other',
'6': 'Rangeland'
};

var cpDict = {
  '0': 'No Data',
  '1': 'Stable',
  '2':'Growth/recovery',
  '3': 'Fire',
  '4': 'Harvest',
  '5': 'Other'
}

  // if(dataTableT[0].length > 5){
  if(analysisMode === 'advanced'){
    // console.log('convertinggggggg tabbbbbbbble' );
    var isFirst = true;
    dataTableT = dataTableT.map(function(i){if(isFirst === false){i[3] = lcDict[Math.round(i[3]*10)]};isFirst = false;return i});
    var isFirst = true;
    dataTableT = dataTableT.map(function(i){if(isFirst === false){i[4] = luDict[Math.round(i[4]*10)]};isFirst = false;return i});
    var isFirst = true;
    // dataTableT = dataTableT.map(function(i){if(isFirst === false){i[5] = cpDict[parseInt(i[5]*10)]};isFirst = false;return i});
//       dataTableT = dataTableT.map(function(i){i[2] = cdlDict[i[2]];return i})
  }
  

      return dataTableT
    };




///////////////////////////////////////////////////////////////////
//Function to compute range list on client side
function range(start, stop, step){
  start = parseInt(start);
  stop = parseInt(stop);
    if (typeof stop=='undefined'){
        // one param defined
        stop = start;
        start = 0;
    }
    if (typeof step=='undefined'){
        step = 1;
    }
    if ((step>0 && start>=stop) || (step<0 && start<=stop)){
        return [];
    }
    var result = [];
    for (var i=start; step>0 ? i<stop : i>stop; i+=step){
        result.push(i);
    }
    return result;
}

function llToNAD83(x,y){
      var vertex = [x,y];
      var smRadius = 6378136.98;
      var smRange = smRadius * Math.PI * 2.0;
      var smLonToX = smRange / 360.0;
      var smRadiansOverDegrees = Math.PI / 180.0;


      // compute x-map-unit
      vertex[0] *= smLonToX;

      var y = vertex[1];

      // compute y-map-unit
      if (y > 86.0)
      {
      vertex[1] = smRange;
      }
      else if (y < -86.0)
      {
      vertex[1] = -smRange;
      }
      else
      {
      y *= smRadiansOverDegrees;
      y = Math.log(Math.tan(y) + (1.0 / Math.cos(y)), Math.E);
      vertex[1] = y * smRadius; 
      }
      return {'x':vertex[0],'y':vertex[1]}
    }
//From:https://stackoverflow.com/questions/12199051/merge-two-arrays-of-keys-and-values-to-an-object-using-underscore answer 6
var toObj = (ks, vs) => ks.reduce((o,k,i)=> {o[k] = vs[i]; return o;}, {});
var toDict = toObj;
////////////////////////////////////////
function CopyAnArray (ari1) {
   var mxx4 = [];
   for (var i=0;i<ari1.length;i++) {
      var nads2 = [];
      for (var j=0;j<ari1[0].length;j++) {
         nads2.push(ari1[i][j]);
      }
      mxx4.push(nads2);
   }
   return mxx4;
}
function arrayColumn(arr,i){return arr.map(function(r){return r[i]})};
//Source: http://bcdcspatial.blogspot.com/2012/01/onlineoffline-mapping-map-tiles-and.html
function tileXYZToQuadKey(x, y, z){
        var quadKey = '';
         for(var i = z;i > 0;i--){
             var digit = 0;
              var mask = 1 << (i - 1);
              // print(mask);
              // print(i);
              if((x & mask)  != 0){
                        digit = digit + 1
                      }
              // print((x & mask))
              // print(digit)
              if((y & mask) != 0){
                        digit =digit + 2
                    
                  }
              // print(digit)
              quadKey = quadKey  + digit.toString();
            }
                return quadKey
       }

//Function for centering map
function centerMap(lng,lat,zoom){
    map.setCenter({lat:lat,lng:lng});
    map.setZoom(zoom);
}
function synchronousCenterObject(feature){

    var bounds = new google.maps.LatLngBounds(); 
    
    feature.coordinates[0].map(function(latlng){
     bounds.extend({lng:latlng[0], lat:latlng[1]});
    });

    map.fitBounds(bounds);
}

function centerObject(fc){
  try{
    // Map2.addLayer(ee.FeatureCollection([ee.Feature(fc.geometry())]))
    // $('#summary-spinner').show();
    fc.geometry().bounds().evaluate(function(feature){synchronousCenterObject(feature);
      // $('#summary-spinner').hide();
    });
  }
  catch(err){
    // alert('Bad Fusion Table');
    console.log(err);
   
  }
  
}




//Function for creating color ramp generally for a map legend
function createColorRamp(styleName, colorList, width,height){
    var myCss = 
        
        "background-image:linear-gradient(to right, ";
     
    for(var i = 0; i< colorList.length;i++){myCss = myCss + '#'+colorList[i].toLowerCase() + ',';}
    myCss = myCss.slice(0,-1) + ");";



return myCss
}
//////////////////////////////////////////////////////
//Function to convert csv, kml, shp to geoJSON
function convertToGeoJSON(formID){
  var url = 'https://ogre.adc4gis.com/convert'

  var data = new FormData();
  data.append("targetSrs","EPSG:4326");
// data.append("sourceSrs",'');
  jQuery.each(jQuery('#'+formID)[0].files, function (i, file) {
   
    data.append("upload", file);
  });
  
  var out= $.ajax({
    type: 'POST',
    url: url,
    data: data,
    processData: false,
    contentType: false
  });
  // console.log('out');console.log(out);
  
  return out;
}

//////////////////////////////////////////////////////
//Wrappers for printing and printing to console
function printImage(message){print(message)};
function print(message){
    console.log(message)
}
/////////////////////////////////////////////////////
function getRandomArbitrary(min, max) {
    return Math.random() * (max - min) + min;
}
    function clearPlots(){
var plotElements = document.getElementById("pt-list");;
                print(plotElements);
                while(plotElements.firstChild){
                    // print('removing')
                    plotElements.removeChild(plotElements.firstChild);
                    }
    plotDictID = 1;
    plotIDList = [];
    plotID =1;
}

function addPlotProject(plotProjectName,plotProjectPts){
  
  var projectElement = document.createElement("ee-pt-project");
  projectElement.name = plotProjectName;
  projectElement.plotList = plotProjectPts;
  projectElement.ID = plotProjectID;
  var ptList = document.querySelector("pt-project-list");
  ptList.insertBefore(projectElement,ptList.firstChild);
  plotProjectID++;

}
// function addPlot(latLng){
//   // plotDict[plotDictID] = false;
 
//   var ptElement = document.createElement("ee-pt");
  
//   ptElement.name = latLng;
//   // print(latLng);
//   ptElement.ID = plotDictID;
//   // ptElement.isOn = false;
//   var ptList = document.querySelector("pt-list");
//     ptList.insertBefore(ptElement,ptList.firstChild);
//    plotDictID ++;
// }
function setPlotColor(ID){
    var plotElements = document.getElementsByTagName("ee-pt");
      
  for(var i = 0;i<plotElements.length;i++){
    plotElements[i].style.outline = 'none';
    
  }
  // console.log(plotElements[0])
  plotElements[plotElements.length-ID].style.outline = '#FFF solid';
   
}
function setPlotProjectColor(ID){
    var plotElements = document.getElementsByTagName("ee-pt-project");
      
  for(var i = 0;i<plotElements.length;i++){
    plotElements[i].style.outline = 'none';
    
  }
  // console.log(plotElements[0])
  plotElements[plotElements.length-ID].style.outline = '#FFF dotted';
   
}

function addSelectLayerToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem){
  viz.canQuery = false;
  viz.isSelectLayer = true;
  // selectLayers[name] = {'item':item,'viz':viz,'features':[]}
  // var id = name.replaceAll(' ','-');
  addToMap(item,viz,name,visible,label,fontColor,helpBox,'area-charting-select-layer-list',queryItem);
 
}
var intervalPeriod = 666.6666666666666;
var timeLapseID;
var timeLapseFrame = 0;
var cumulativeMode = true;
function pauseTimeLapse(id){
  if(id === null || id === undefined){id = timeLapseID}
    timeLapseID = id;
  if(timeLapseObj[timeLapseID].isReady){
      pauseAll();
      clearActiveButtons();
      $('#'+timeLapseID+'-pause-button').addClass('time-lapse-active');
    }
  } 
function setFrameOpacity(frame,opacity){
  var s = $('#'+frame).slider();
  s.slider('option', 'value',opacity);
  s.slider('option','slide').call(s,null,{ handle: $('.ui-slider-handle', s), value: opacity });
}

function selectFrame(id,fromYearSlider,advanceOne){

  if(id === null || id === undefined){id = timeLapseID}
  if(fromYearSlider === null || fromYearSlider === undefined){fromYearSlider = false}
  if(advanceOne === null || advanceOne === undefined){advanceOne = true}
  timeLapseID = id
  
  if(timeLapseID !== undefined && timeLapseObj[timeLapseID].isReady){
    turnOffLayers();
    turnOnTimeLapseLayers();
    var slidersT = timeLapseObj[timeLapseID].sliders;
    if(timeLapseFrame > slidersT.length-1){timeLapseFrame = 0}
    else if(timeLapseFrame < 0){timeLapseFrame = slidersT.length-1}

    if(!eval(cumulativeMode) || timeLapseFrame === 0){
      slidersT.map(function(s){
        try{
          setFrameOpacity(s,0)
        }catch(err){}
        
      });
    }else{
      slidersT.slice(0,timeLapseFrame).map(function(s){
        try{
          setFrameOpacity(s,timeLapseObj[timeLapseID].opacity)
        }catch(err){}
        
      })
    }
    
    var frame = slidersT[timeLapseFrame];
    
    try{
        setFrameOpacity(frame,timeLapseObj[timeLapseID].opacity);
        if(!fromYearSlider){
          Object.keys(timeLapseObj).map(function(k){
            var s = $('#'+k+'-year-slider').slider();
            s.slider('option', 'value',timeLapseObj[k].years[timeLapseFrame]);
            $('#'+k+'-year-slider-handle-label').text( timeLapseObj[k].years[timeLapseFrame])

          })
        }
        
        
        
      }catch(err){}
    $('#'+timeLapseID+'-year-label').show();
    // $('#'+timeLapseID+'-year-label').html(timeLapseObj[timeLapseID].years[timeLapseFrame])
    $('#time-lapse-year-label').show();
    $('#time-lapse-year-label').html(`Time lapse year: ${timeLapseObj[timeLapseID].years[timeLapseFrame]}`)
    // if(advanceOne){timeLapseFrame++};
  }
  
}
function advanceOneFrame(){
  timeLapseFrame++;
  selectFrame()
}
function pauseButtonFunction(id){
  if(id === null || id === undefined){id = timeLapseID}
  
  timeLapseID = id;
  if(timeLapseID !== undefined && timeLapseObj[timeLapseID].isReady){
    // timeLapseFrame--;
    clearAllFrames();
    pauseTimeLapse();
    // year++;
    selectFrame();
    alignTimeLapseCheckboxes();
    timeLapseObj[timeLapseID].state = 'paused';
  }

}
function pauseAll(){
  Object.keys(timeLapseObj).map(function(k){
    if(timeLapseObj[k].intervalValue !== null && timeLapseObj[k].intervalValue !== undefined){
      window.clearInterval(timeLapseObj[k].intervalValue);
    }
    timeLapseObj[k].intervalValue = null;
  })
}
function forwardOneFrame(id){
    timeLapseID = id;
    if(timeLapseObj[timeLapseID].isReady){
      clearAllFrames();
      pauseTimeLapse();
      // year++;
      advanceOneFrame();
      alignTimeLapseCheckboxes();
    }
  };
function backOneFrame(id){
    timeLapseID = id;
    if(timeLapseObj[timeLapseID].isReady){
      clearAllFrames();
      pauseTimeLapse();

      timeLapseFrame--;
      selectFrame();
      alignTimeLapseCheckboxes();
    }
  };
function clearActiveButtons(){
   Object.keys(timeLapseObj).map(function(k){
    $('#'+k+'-pause-button').removeClass('time-lapse-active');
    $('#'+k+'-play-button').removeClass('time-lapse-active');
    if(k === timeLapseID){
      $('#'+k+'-stop-button').removeClass('time-lapse-active');
    }
    
   })
};
function clearAllFrames(){
  turnOffAllNonActiveTimeLapseLayers(); 
  
  Object.keys(timeLapseObj).map(function(k){
    var slidersT = timeLapseObj[k].sliders;
    $('#'+k+'-year-label').hide();
    $('#'+k+'-stop-button').addClass('time-lapse-active');
    $('#'+k+'-pause-button').removeClass('time-lapse-active');
    $('#'+k+'-play-button').removeClass('time-lapse-active');
    timeLapseObj[k].state = 'inactive';
    slidersT.map(function(s){
      try{setFrameOpacity(s,0)}
      catch(err){}
      
    })
  })
}
function setSpeed(id,speed){
  timeLapseID = id;
  intervalPeriod = speed;
  if(timeLapseObj[timeLapseID].isReady){
    pauseAll();
    playTimeLapse(id);
  }
}
function playTimeLapse(id){
   if(id === null || id === undefined){id = timeLapseID}
  
  timeLapseID = id;
  if(timeLapseID !== undefined && timeLapseObj[timeLapseID].isReady){
    clearAllFrames();
    pauseAll();
    timeLapseObj[timeLapseID].state = 'play';
    selectFrame(null,null,false);
    if(timeLapseObj[id].intervalValue === null || timeLapseObj[id].intervalValue === undefined){
        timeLapseObj[id].intervalValue =window.setInterval(advanceOneFrame, intervalPeriod);
      }
      $('#'+id+'-stop-button').removeClass('time-lapse-active');
      $('#'+id+'-pause-button').removeClass('time-lapse-active');
      $('#'+id+'-play-button').addClass('time-lapse-active');
      alignTimeLapseCheckboxes();
  }
}
function stopTimeLapse(id){
  $('#time-lapse-year-label').empty();
  $('#time-lapse-year-label').hide();
  timeLapseID = null;
  // turnOffAllTimeLapseLayers();
  pauseAll();
  clearAllFrames();
}
function toggleTimeLapseLayers(id){
  if(id === null || id === undefined){id = timeLapseID}
  var visibleToggles = timeLapseObj[k].layerVisibleIDs;
  visibleToggles.map(function(i){$('#'+i).click()});
}
function toggleAllTimeLapseLayers(){
  Object.keys(timeLapseObj).map(function(k){
    toggleTimeLapseLayers(k)
  })
}
// function turnOnAllTimeLapseLayers(){
//   Object.keys(timeLapseObj).map(function(k){
//     turnOnTimeLapseLayers(k)
//   })
// };
function turnOffAllTimeLapseLayers(){
  Object.keys(timeLapseObj).map(function(k){
    turnOffTimeLapseLayers(k)
  })
}
function turnOffAllNonActiveTimeLapseLayers(){
  Object.keys(timeLapseObj).map(function(k){
    if(k !== timeLapseID){
      turnOffTimeLapseLayers(k);
    }
  })
}
function toggleTimeLapseLayers(id){
  if(id === null || id === undefined){id = timeLapseID}
  if(timeLapseObj[id].isReady){
    timeLapseObj[id].layerVisibleIDs.map(function(i){$('#'+i).click()});
    if(timeLapseObj[id].visible){
      timeLapseObj[id].visible = false
    }else{timeLapseObj[id].visible = true}
  }
}
function turnOnTimeLapseLayers(id){
  if(id === null || id === undefined){id = timeLapseID}
  if(timeLapseObj[id].isReady){
    
    if(timeLapseObj[id].visible === false){
      timeLapseObj[id].visible = true;
      timeLapseObj[id].layerVisibleIDs.map(function(i){$('#'+i).click()});
    }
  }
}
function turnOffTimeLapseLayers(id){
  if(id === null || id === undefined){id = timeLapseID}
  if(timeLapseObj[id].isReady){
    
    if(timeLapseObj[id].visible === true){
      timeLapseObj[id].visible = false;
      timeLapseObj[id].layerVisibleIDs.map(function(i){$('#'+i).click()});
    }
  }
}
var lastJitter;
function jitterZoom(){
  if(lastJitter === null || lastJitter === undefined){
    lastJitter = new Date();
  }
  var tDiff = new Date() - lastJitter;
  var jittered = false;
  if((tDiff > 3000 && geeTileLayersDownloading === 0) || tDiff > 10000){
    console.log(tDiff)
    console.log('jittering zoom')
    var z = map.getZoom();
    map.setZoom(z-1);
    map.setZoom(z);
    jittered = true;
    lastJitter = new Date();
  }
  
  return jittered
  
}
function alignTimeLapseCheckboxes(){
  Object.keys(timeLapseObj).map(function(k){
    if(timeLapseObj[k].isReady){
      var checked = false;
      if(timeLapseObj[k].visible){
        checked = true;
        $('#'+k+'-time-lapse-layer-range-container').slideDown();
        $('#'+k+'-icon-bar').slideDown();
        $('#'+k+'-collapse-label').addClass('time-lapse-label-container');
      }
      else{
        $('#'+k+'-collapse-label').css('background',`-webkit-linear-gradient(left, #FFF, #FFF ${0}%, transparent ${0}%, transparent 100%)`);
        $('#'+k+'-time-lapse-layer-range-container').slideUp();
        $('#'+k+'-icon-bar').slideUp();
        $('#'+k+'-collapse-label').removeClass('time-lapse-label-container');
        $('#'+k+'-loading-spinner').hide();
        $('#'+k+'-loading-gear').hide();
      }
        
      $('#'+k+'-toggle-checkbox').prop('checked', checked);
    }
  })
}
function timeLapseCheckbox(id){
  var v = timeLapseObj[id].visible;
  if(!v){
    pauseButtonFunction(id);

  }else{
    stopTimeLapse(id);
  }
  alignTimeLapseCheckboxes();
}
function toggleFrames(id){
  $('#'+id+'-collapse-div').toggle();
}
function turnOffTimeLapseCheckboxes(){
  Object.keys(timeLapseObj).map(function(k){
    if(timeLapseObj[k].isReady){
      if(timeLapseObj[k].visible){
        stopTimeLapse(k);
      }
    }
    
  });
  alignTimeLapseCheckboxes();
}
function toggleCumulativeMode(){
  if(cumulativeMode){
    $('.cumulativeToggler').removeClass('time-lapse-active');
    cumulativeMode = false;
  }else{
    $('.cumulativeToggler').addClass('time-lapse-active');
    cumulativeMode = true;
  }
  // timeLapseFrame--;
  selectFrame();
  
}
function addTimeLapseToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem){
  if(viz !== null && viz !== undefined && viz.serialized !== null && viz.serialized !== undefined && viz.serialized === true){
        item = ee.Deserializer.fromJSON(JSON.parse(JSON.stringify(item)));
        viz.serialized = false;
    }
  if(viz.cumulativeMode === null || viz.cumulativeMode === undefined){viz.cumulativeMode = true}
  // if(visible === undefined || visible === null){
    var visible = false;
  // };
  if(viz.opacity === undefined || viz.opacity === null){viz.opacity = 1}
   
  var checked = '';
  if(visible){checked = 'checked'}
  var legendDivID = name.replaceAll(' ','-')+ '-' +NEXT_LAYER_ID.toString() ;
  legendDivID = legendDivID.replaceAll('/','-');
  legendDivID = legendDivID.replaceAll('(','-');
  legendDivID = legendDivID.replaceAll(')','-');
  viz.canQuery = true;
  viz.isSelectLayer = false;
  viz.isTimeLapse = true;
  viz.timeLapseID = legendDivID;
  viz.layerType = 'geeImage';
  

  timeLapseObj[legendDivID] = {}
  if(whichLayerList === null || whichLayerList === undefined){whichLayerList = "layer-list"}  

  if(viz.years === null || viz.years === undefined){
    console.log('start computing years')
    viz.years = item.sort('system:time_start',true).toList(10000,0).map(function(img){return ee.Date(ee.Image(img).get('system:time_start')).get('year')}).getInfo();
    console.log('done computing years')
  }
  
  var startYearT = viz.years[0];
  var endYearT = viz.years[viz.years.length-1]
  timeLapseObj[legendDivID].years = viz.years;
  timeLapseObj[legendDivID].frames = ee.List.sequence(0,viz.years.length-1).getInfo();
  timeLapseObj[legendDivID].nFrames = viz.years.length;
  timeLapseObj[legendDivID].loadingLayerIDs = [];
  timeLapseObj[legendDivID].loadingTilesLayerIDs = [];
  timeLapseObj[legendDivID].layerVisibleIDs = [];
  timeLapseObj[legendDivID].sliders = [];
  timeLapseObj[legendDivID].intervalValue = null;
  timeLapseObj[legendDivID].isReady = false;
  timeLapseObj[legendDivID].visible = visible;
  timeLapseObj[legendDivID].state = 'inactive';
  timeLapseObj[legendDivID].opacity = viz.opacity*100;
  var layerContainerTitle = 'Time lapse layers load multiple map layers throughout time. Once loaded, you can play the time lapse as an animation, or advance through single years using the buttons and sliders provided.  The layers can be displayed as a single year or as a cumulative mosaic of all preceding years using the right-most button.'
  $('#'+whichLayerList).append(`
                                <li   title = '${layerContainerTitle}' id = '${legendDivID}-collapse-label' class = 'layer-container'>
                                 
                                  

                                  <div class = 'time-lapse-layer-range-container' >
                                    <div title = 'Opacity' id='${legendDivID}-opacity-slider' class = 'simple-time-lapse-layer-range-first'>
                                      <div id='${legendDivID}-opacity-slider-handle' class=" time-lapse-slider-handle ui-slider-handle">
                                        <div style = 'display:none;' id='${legendDivID}-opacity-slider-handle-label' class = 'time-lapse-slider-handle-label'>${timeLapseObj[legendDivID].opacity/100}</div>
                                      </div>
                                    </div>
                                    <div id='${legendDivID}-time-lapse-layer-range-container' style = 'display:none;'>
                                      <div title = 'Frame Year' id='${legendDivID}-year-slider' class = 'simple-time-lapse-layer-range'>
                                        <div id='${legendDivID}-year-slider-handle' class=" time-lapse-slider-handle ui-slider-handle">
                                          <div id='${legendDivID}-year-slider-handle-label' class = 'time-lapse-slider-handle-label'>${viz.years[0]}</div>
                                        </div>
                                      </div>
                                    
                                      <div title = 'Frame Rate' id='${legendDivID}-speed-slider' class = 'simple-time-lapse-layer-range'>
                                        <div id='${legendDivID}-speed-slider-handle' class=" time-lapse-slider-handle ui-slider-handle">
                                          <div id='${legendDivID}-speed-slider-handle-label' class = 'time-lapse-slider-handle-label'>${(1/(intervalPeriod/1000)).toFixed(1)}fps</div>
                                        </div>
                                      </div>
                                    </div>
                                  </div>

                                    
                                  <input  id="${legendDivID}-toggle-checkbox" onchange = 'timeLapseCheckbox("${legendDivID}")' type="checkbox" ${checked}  />
                                  <label  title = 'Activate/deactivate time lapse' id="${legendDivID}-toggle-checkbox-label" style = 'margin-bottom:0px;display:none;'  for="${legendDivID}-toggle-checkbox"></label>
                                  <i style = 'display:none;' id = '${legendDivID}-loading-gear' title = '${name} time lapse tiles loading' class="text-dark fa fa-gear fa-spin layer-spinner"></i>
                                  <i id = '${legendDivID}-loading-spinner' title = '${name} time lapse layers loading' class="text-dark fa fa-spinner fa-spin layer-spinner"></i>

                                  <span  id = '${legendDivID}-name-span'  class = 'layer-span'>${name}</span>

                                  <div id = "${legendDivID}-icon-bar" class = 'icon-bar pl-4 pt-3' style = 'display:none;'>
                                    <button class = 'btn' title = 'Back one frame' id = '${legendDivID}-backward-button' onclick = 'backOneFrame("${legendDivID}")'><i class="fa fa-backward fa-xs"></i></button>
                                    <button class = 'btn' title = 'Pause animation' id = '${legendDivID}-pause-button' onclick = 'pauseButtonFunction("${legendDivID}")'><i class="fa fa-pause"></i></button>
                                    <button style = 'display:none;' class = 'btn time-lapse-active' title = 'Clear animation' id = '${legendDivID}-stop-button' onclick = 'stopTimeLapse("${legendDivID}")'><i class="fa fa-stop"></i></button>
                                    <button class = 'btn' title = 'Play animation' id = '${legendDivID}-play-button'  onclick = 'playTimeLapse("${legendDivID}")'><i class="fa fa-play"></i></button>
                                    <button class = 'btn' title = 'Forward one frame' id = '${legendDivID}-forward-button' onclick = 'forwardOneFrame("${legendDivID}")'><i class="fa fa-forward"></i></button>
                                    <button style = '' class = 'btn' title = 'Refresh layers if tiles failed to load' id = '${legendDivID}-refresh-tiles-button' onclick = 'jitterZoom()'><i class="fa fa-refresh"></i></button>
                                    <button style = 'display:none;' class = 'btn' title = 'Toggle frame visiblity' id = '${legendDivID}-toggle-frames-button' onclick = 'toggleFrames("${legendDivID}")'><i class="fa fa-eye"></i></button>
                                    <button class = 'btn cumulativeToggler time-lapse-active' onclick = 'toggleCumulativeMode()' title = 'Click to toggle whether to show a single year or all years in the past along with current year'><img style = 'width:1.4em;filter: invert(100%) brightness(500%)'  src="images/cumulative_icon.png"></button>
                                    <div id = "${legendDivID}-cumulative-radio-container" class = 'pt-2'></div>
                                  </div>

                                </li>
                                
                                <li id = '${legendDivID}-collapse-div' style = 'display:none;'></li>`)
  
  
 
  // addMultiRadio(legendDivID+'-collapse-label',legendDivID+'-cumulative-radio','',legendDivID'-cumulativeMode',{"Single-Year":!viz.cumulativeMode,"Cumulative":viz.cumulativeMode})
  // addRadio(legendDivID+'-cumulative-radio-container',legendDivID+'-cumulative-radio','','Single Year','Cumulative','cumulativeMode',false,true,'setCumulativeMode()','setCumulativeMode()','Toggle whether to show a single year or all years in the past along with current year')
  // $('#'+legendDivID+'-cumulative-radio-first_toggle_label').addClass('cumulative-off');
  // $('#'+legendDivID+'-cumulative-radio-second_toggle_label').addClass('cumulative-on');
  // $('#'+legendDivID+'-cumulative-radio').addClass('pt-4');
  $('#time-lapse-legend-list').append(`<div id="legend-${legendDivID}-collapse-div"></div>`);
  onclick = 'timeLapseCheckbox("${legendDivID}")'
  var prevent = false;
  var delay = 200;
  $('#'+ legendDivID + '-name-span').click(function(){
    // showMessage('test')
    setTimeout(function(){
      if(!prevent){
        timeLapseCheckbox(legendDivID);
      }
    },delay)
    
  });
  $('#'+ legendDivID + '-name-span').dblclick(function(){
    showMessage('test')
      // zoomFunction();
      // prevent = true;
      // zoomFunction();
      // if(!timeLapseObj[legendDivID].visible){$('#'+legendDivID+'-toggle-checkbox').click();}
      // setTimeout(function(){prevent = false},delay)
    })
  // viz.opacity = 0;
  viz.layerType = 'geeImage';
  viz.legendTitle = name;
  viz.opacity = 0;

  if(viz.timeLapseType === 'tileMapService'){
    viz.layerType = 'tileMapService';
    viz.years.map(function(yr){
      if(yr !== viz.years[0]){
        viz.addToLegend = false;
        viz.addToClassLegend = false;
        
      }
        addToMap(standardTileURLFunction(item + yr.toString()+'/',true,''),viz,name +' '+   yr.toString(),visible,label ,fontColor,helpBox,legendDivID+'-collapse-div',queryItem)
      
     }) 
  }else{
    viz.years.map(function(yr){
      var img = ee.Image(item.filter(ee.Filter.calendarRange(yr,yr,'year')).first()).set('system:time_start',ee.Date.fromYMD(yr,6,1).millis());
      

      if(yr !== viz.years[0]){
        viz.addToLegend = false;
        viz.addToClassLegend = false;
        
      }
      // console.log(viz);
      
        
        addToMap(img,viz,name +' '+   yr.toString(),visible,label ,fontColor,helpBox,legendDivID+'-collapse-div',queryItem);
     
    })
  }
  if(viz.timeLapseType === 'tileMapService'){
    timeLapseObj[legendDivID].isReady = true;
    $('#'+legendDivID+'-toggle-checkbox-label').show();
    $('#'+legendDivID+'-loading-spinner').hide();
  }
  // timeLapseObj[legendDivID].years = timeLapseObj[legendDivID].years;
    timeLapseObj[legendDivID].sliders = timeLapseObj[legendDivID].sliders;
     $('#'+legendDivID+'-opacity-slider').slider({
        
        min: 0,
        max: 1,
        step: 0.05,
        value: timeLapseObj[legendDivID].opacity/100,
        slide: function(e,ui){
          // console.log(e);
          var opacity = ui.value;
          var k = legendDivID;
          // Object.keys(timeLapseObj).map(function(k){
            var s = $('#'+k+'-opacity-slider').slider();
            s.slider('option', 'value',ui.value);
            $('#'+k+'-opacity-slider-handle-label').text(opacity);
            timeLapseObj[k].opacity = opacity*100
          // });
          selectFrame(null,null,false)
          // if(timeLapseObj[legendDivID].isReady){
          //   clearAllFrames();
          //   pauseTimeLapse(legendDivID);
          //   selectFrame(legendDivID,true);
          //   alignTimeLapseCheckboxes();
          // }
        }
      });
    $('#'+legendDivID+'-year-slider').slider({
        
        min: startYearT,
        max: endYearT,
        step: 1,
        value: startYearT,
        slide: function(e,ui){
          // console.log(e);
          var yr = ui.value;
          var i = viz.years.indexOf(yr);
          timeLapseFrame = i;
          Object.keys(timeLapseObj).map(function(k){
            var s = $('#'+k+'-year-slider').slider();
            s.slider('option', 'value',ui.value);
            $('#'+k+'-year-slider-handle-label').text( ui.value )
          })
          if(timeLapseObj[legendDivID].isReady){
            clearAllFrames();
            pauseTimeLapse(legendDivID);
            selectFrame(legendDivID,true,false);
            alignTimeLapseCheckboxes();
          }
        }
      });
    $('#'+legendDivID+'-speed-slider').slider({
        min: 0.5,
        max: 3.0  ,
        step: 0.5,
        value: 1.5,
        slide: function(e,ui){
          // console.log(e);
          var speed = 1/ui.value*1000;
          Object.keys(timeLapseObj).map(function(k){
            var s = $('#'+k+'-speed-slider').slider();
            s.slider('option', 'value',ui.value);
            $('#'+k+'-speed-slider-handle-label').text(`${ui.value.toFixed(1)}fps`)
          })
           
    // sliders = sliders.map(function(s){return sliders[s].id})
          if(timeLapseObj[legendDivID].isReady){
            setSpeed(legendDivID,speed)
          }
        }
      });

   
 
  
}
/////////////////////////////////////
function addExport(eeImage,name,res,Export,metadataParams){

  var exportElement = {};
  if(metadataParams === null || metadataParams === undefined){
    metadataParams = {'studyAreaName':studyAreaName,'version':'v2019.1','summaryMethod':summaryMethod,'whichOne':'Gain Year','startYear':startYear,'endYear':endYear,'description':'this is a description'}
  }
  if(Export === null || Export === undefined){
    Export = true;
  }
  var checked = '';
  if(Export){checked = 'checked'}
  
  var now = Date().split(' ');
  var nowSuffix = '_'+now[2]+'_'+now[1]+'_'+now[3]+'_'+now[4]

  name = name;//+ nowSuffix
  name = name.replace(/\s+/g,'_')
  name = name.replaceAll('(','_')
  name = name.replaceAll(')','_')
  exportElement.res = res;
  exportElement.name = name;
 
  exportElement.eeImage = eeImage;

  exportElement.Export = Export;
  exportElement.ID = exportID;
  
  exportImageDict[exportID] = {'eeImage':eeImage,'name':name,'res':res,'shouldExport':Export,'metadataParams':metadataParams}
  // var exportList = document.querySelector("export-list");
  $('#export-list').append(`<div class = 'input-group'>
                              <span  class="input-group-addon">
                                <input  id = '${name}-checkbox' type="checkbox" ${checked} >
                                <label  style = 'margin-bottom:0px;'  for='${name}-checkbox'></label>
                              </span>
                              
                              <input  id = '${name}-name' class="form-control export-name-input" type="text" value="${exportElement.name}" rel="txtTooltip" title = 'Change export name if needed'>
                            </div>`)
  $('#' + name + '-name').on('input', function() {
    exportImageDict[exportElement.ID].name = $(this).val()
  })
  $('#' + name + '-checkbox').on('change', function() {
   
    exportImageDict[exportElement.ID].shouldExport = this.checked
  })
    // exportList.insertBefore(exportElement,exportList.firstChild);
  exportID ++;
}
function addImageDownloads(imagePathJson){
  
}
/////////////////////////////////////////////////////
//Function to add ee object ot map
function addToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem){
    if(viz !== null && viz !== undefined && viz.serialized !== null && viz.serialized !== undefined && viz.serialized === true){
        item = ee.Deserializer.fromJSON(JSON.parse(JSON.stringify(item)));
    }
    var currentGEERunID = geeRunID;
    if(whichLayerList === null || whichLayerList === undefined){whichLayerList = "layer-list"}
    // print(item.getInfo().type)
    // if(item.getInfo().type === 'ImageCollection'){print('It is a collection')}
    if(viz === null || viz === undefined){viz = {}}
    if(name == null){
        name = "Layer "+NEXT_LAYER_ID;
        
    }
    //Possible layerType: geeVector,geoJSONVector,geeImage,geeImageCollection,tileMapService,dynamicMapService

    if(viz.layerType === null || viz.layerType === undefined){
      try{var t = item.bandNames();viz.layerType = 'geeImage'}
    // catch(err){
      // try{
      //   var t = ee.Image(item.first()).bandNames().getInfo();
      //   item = item.mosaic();
      //   // isImageCollection = true;
      // }
      catch(err2){
        try{
          var t = ee.Image(item.first()).bandNames().getInfo();
          // print(t.getInfo())
          viz.layerType = 'geeImageCollection';
        
        }
        //Check if its a geometry
        catch(err3){
          try{
             var t = item.geometry().getInfo();
            
          }catch(err4){
            // console.log('geo');
            item = ee.FeatureCollection(item);
            viz.canQuery = false;
          }
          //Check if its a feature or featureCollection
          // try{
          //   var n = item.limit(501).size().getInfo();
          //   if(n > 500){
          //     viz.layerType = 'geeVectorImage';
          //   }
          //   // console.log('featureCollection')
          // }catch(err5){
          //   // console.log('feature')
          //   item = ee.FeatureCollection([item])
          // }
          viz.layerType = 'geeVector';
        }
        
       
        }
    }
    if(viz.layerType === 'geoJSONVector'){viz.canQuery = false;}
    // console.log(viz.layerType);
    // console.log(viz.layerType);console.log(name);
    //Take care of vector option
    // var isVector = false;
    // var isImageCollection = false;
    // var isTileMapService = false;
    // var isDynamicMapService = false;
    // if(viz.isTileMapService === true){isTileMapService = true}
    // else if(viz.isDynamicMapService === true){isDynamicMapService = true;}
    // else if(viz.)
    // else if(!isTileMapService && !isDynamicMapService ){
    //   try{var t = item.bandNames();}
    // // catch(err){
    //   // try{
    //   //   var t = ee.Image(item.first()).bandNames().getInfo();
    //   //   item = item.mosaic();
    //   //   // isImageCollection = true;
    //   // }
    //   catch(err2){
    //     if(!isTileMapService){ isVector = true;}
       
    //     }
    // }
    

      // };
    // console.log(name + ' ' + isVector + isImageCollection+isTileMapService)
    if(viz.layerType === 'geeVector' || viz.layerType === 'geoJSONVector'){
      if(viz.strokeOpacity === undefined || viz.strokeOpacity === null){viz.strokeOpacity = 1};
      if(viz.fillOpacity === undefined || viz.fillOpacity === null){viz.fillOpacity = 0.2};
      if(viz.fillColor === undefined || viz.fillColor === null){viz.fillColor = '222222'};
      if(viz.strokeColor === undefined || viz.strokeColor === null){viz.strokeColor = getColor()};
      if(viz.strokeWeight === undefined || viz.strokeWeight === null){viz.strokeWeight = 3};
      viz.opacityRatio = viz.strokeOpacity/viz.fillOpacity;
      if(viz.fillColor.indexOf('#') == -1){viz.fillColor = '#' + viz.fillColor};
      if(viz.strokeColor.indexOf('#') == -1){viz.strokeColor = '#' + viz.strokeColor};
      if(viz.addToClassLegend === undefined || viz.addToClassLegend === null){
        viz.addToClassLegend = true;
        
      }
    }else if(viz.layerType === 'geeVectorImage' ){
      if(viz.strokeOpacity === undefined || viz.strokeOpacity === null){viz.strokeOpacity = 1};
      viz.fillOpacity = 0;
      if(viz.fillColor === undefined || viz.fillColor === null){viz.fillColor = '222222'};
      if(viz.strokeColor === undefined || viz.strokeColor === null){viz.strokeColor = getColor()};
      if(viz.strokeWeight === undefined || viz.strokeWeight === null){viz.strokeWeight = 2};
      if(viz.fillColor.indexOf('#') == -1){viz.fillColor = '#' + viz.fillColor};
      if(viz.strokeColor.indexOf('#') == -1){viz.strokeColor = '#' + viz.strokeColor};
      if(viz.addToClassLegend === undefined || viz.addToClassLegend === null){
        viz.addToClassLegend = true;viz.addToLegend = false;
        
      }
    }


    var legendDivID = name.replaceAll(' ','-')+ '-' +NEXT_LAYER_ID.toString() ;
    
    legendDivID = legendDivID.replaceAll('/','-');
    legendDivID = legendDivID.replaceAll('(','-');
    legendDivID = legendDivID.replaceAll(')','-');
    if(visible == null){
        visible = true;
    }
    if(viz.opacity == null){
      viz.opacity = 1;
    }
    
    var layerObjKeys = Object.keys(layerObj);
    var nameIndex = layerObjKeys.indexOf(name);
    if(nameIndex   != -1){
      visible = layerObj[name][0];
      viz.opacity = layerObj[name][1];
      if(viz.layerType === 'geeVector' || viz.layerType === 'geoJSONVector'){
        viz.strokeOpacity =  layerObj[name][1];
        viz.fillOpacity = viz.strokeOpacity / viz.opacityRatio;

      }
    }


    if(helpBox == null){helpBox = ''};
    var layer = {};//document.createElement("ee-layer");
    
    layer.ID = NEXT_LAYER_ID;
    NEXT_LAYER_ID += 1;
    layer.layerChildID = layerChildID;
    layerChildID++
    layer.name = name ;
    layer.opacity = viz.opacity;
    viz.opacity = 1;
    layer.map = map;
    layer.helpBoxMessage = helpBox;
    layer.visible = visible;
    layer.label = label;
    layer.fontColor = fontColor;
    layer.helpBox = helpBox;
    layer.legendDivID = legendDivID ;
    if(queryItem === null || queryItem === undefined){queryItem = item};
    if(viz.canQuery === null || viz.canQuery === undefined){viz.canQuery = true};
    layer.canQuery = viz.canQuery;
    layer.queryItem = queryItem;
    layer.layerType = viz.layerType;

    // layer.isTileMapService = isTileMapService;
    // layer.isDynamicMapService = isDynamicMapService;
    // layer.viz = JSON.stringify(viz);
    // layer.viz  = viz;

    // if(viz.min !== null && viz.min !== undefined){
    //   layer.min = viz.min;
    // }
    // else{layer.min = 0;}
    
    if(viz != null && viz.bands == null && viz.addToLegend != false && viz.addToClassLegend != true){
      // console.log('legend-'+whichLayerList)
      addLegendContainer(legendDivID,'legend-'+whichLayerList,false,helpBox)
        // var legendItemContainer = document.createElement("legend-item");

        // legendItemContainer.setAttribute("id", legendDivID);


        // var legendBreak = document.createElement("legend-break");
     
 
      // legendItemContainer.insertBefore(legendBreak,legendItemContainer.firstChild);

        var legend ={};// document.createElement("ee-legend");
         // console.log('here');console.log(viz)
        if(viz.legendTitle !== null && viz.legendTitle !== undefined){
         
          legend.name = viz.legendTitle
        }else{
          legend.name = name;
        }
        
        legend.helpBoxMessage = helpBox
        if(viz.palette != null){
            var palette = viz.palette;
        } else{var palette = '000,FFF';}
        var paletteList = palette;
        if(typeof(palette) === 'string'){paletteList = paletteList.split(',');}
        if(paletteList.length == 1){paletteList = [paletteList[0],paletteList[0]];}
        paletteList = paletteList.map(function(color){if(color.indexOf('#')>-1){color = color.slice(1)};return color});
        var colorRamp = createColorRamp('colorRamp'+colorRampIndex.toString(),paletteList,180,20);
      
        legend.colorRamp = colorRamp;


        if(label != null && viz.min != null){
            legend.min = viz.min + ' ' +label;
        } else if(label != null && viz.min == null){
            legend.min = minLabel;
        } else if(label == null && viz.min != null){
            legend.min = viz.min;
        } 

        if(label != null && viz.max != null){
            legend.max = viz.max + ' ' +label;
        } else if(label != null && viz.max == null){
            legend.max = maxLabel;
        } else if(label == null && viz.max != null){
            legend.max = viz.max;
        } 

        if(viz.legendLabelLeft !== null && viz.legendLabelLeft !== undefined){legend.min = viz.legendLabelLeft + ' ' + viz.min}
        if(viz.legendLabelRight !== null && viz.legendLabelRight !== undefined){legend.max = viz.legendLabelRight + ' ' + viz.max}
        if(legend.min ==null){legend.min = 'min'};
        if(legend.max ==null){legend.max = 'max'};
    
    if(fontColor != null){legend.fontColor = "color:#" +fontColor + ";" }
        else{legend.fontColor    = "color:#DDD;"}
     addColorRampLegendEntry(legendDivID,legend)
    // var legendList = document.querySelector("legend-list");
    // legendItemContainer.insertBefore(legend,legendItemContainer.firstChild);
    // legendList.insertBefore(legendItemContainer,legendList.firstChild);

    
    }

    else if(viz != null && viz.bands == null && viz.addToClassLegend == true){

      addLegendContainer(legendDivID,'legend-'+whichLayerList,false,helpBox)
      var classLegendContainerID = legendDivID + '-class-container';
      var legendClassContainerName;
      if(viz.legendTitle !== null && viz.legendTitle !== undefined){
         
          legendClassContainerName = viz.legendTitle
        }else{
          legendClassContainerName = name;
        }
      addClassLegendContainer(classLegendContainerID,legendDivID,legendClassContainerName)
      // var legendItemContainer = document.createElement("legend-item");
      // legendItemContainer.setAttribute("id", legendDivID);
      // var legendBreak = document.createElement("legend-break");
     
       // var legendList = document.querySelector("legend-list");
      // legendItemContainer.insertBefore(legendBreak,legendItemContainer.firstChild);

      if(viz.layerType !== 'geeVector' && viz.layerType !== 'geoJSONVector' && viz.layerType !== 'geeVectorImage'){
        var legendKeys = Object.keys(viz.classLegendDict);//.reverse();
        legendKeys.map(function(lk){

          var legend = {};//document.createElement("ee-class-legend");
          legend.name = name;
          
          legend.helpBoxMessage = helpBox;


          legend.classColor = viz.classLegendDict[lk];
          legend.classStrokeColor = '999';
          legend.classStrokeWeight = 1;
          legend.className = lk;
          addClassLegendEntry(classLegendContainerID,legend)
          // var legendList = document.querySelector("legend-list");
          // legendItemContainer.insertBefore(legend,legendItemContainer.firstChild);
        })
      }else{
        var legend = {};//document.createElement("ee-class-legend");
        legend.name = name;
        legend.helpBoxMessage = helpBox;
        var strokeColor = viz.strokeColor.slice(1);
        var fillColor = viz.fillColor.slice(1);

        if(strokeColor.length === 3){strokeColor =  strokeColor.split('').map(function(i){return i+i}).join().replaceAll(',','')}
        if(fillColor.length === 3){fillColor =  fillColor.split('').map(function(i){return i+i}).join().replaceAll(',','')}
        
        legend.classColor =  fillColor + Math.floor(viz.fillOpacity/2 * 255).toString(16);
        legend.classStrokeColor = strokeColor+ Math.floor(viz.strokeOpacity * 255).toString(16);
        legend.classStrokeWeight = viz.strokeWeight+1;
        legend.className = '';
   
        addClassLegendEntry(classLegendContainerID,legend)
        // legendItemContainer.insertBefore(legend,legendItemContainer.firstChild);
      }

      

      var title = {};//document.createElement("ee-class-legend-title");
      title.name = name;
      title.helpBoxMessage = helpBox;
      // var legendList = document.querySelector("legend-list");
      // legendItemContainer.insertBefore(title,legendItemContainer.firstChild);
      // legendList.insertBefore(legendItemContainer,legendList.firstChild);
     
    }

   
    layer.visible = visible;
    layer.item = item;
    layer.name = name;
    layer.viz = viz;
    layer.whichLayerList = whichLayerList;
    layer.layerId = layerCount;
    layer.currentGEERunID = currentGEERunID;
    // console.log(whichLayerList);
    addLayer(layer);
    // var layerList = document.querySelector(whichLayerList);
    // layerList.insertBefore(layer,layerList.firstChild);
    layerCount ++;
   
    // print(item)
    
    // if(isVector){item.evaluate(function(v){
    //   if(currentGEERunID === geeRunID){
    //     layer.addToLayerObj(name,visible);
    //     layer.setFeatureLayer(v);
    //     layer.setOpacity();
    //   };
    // })}else{
    //   layer.addToLayerObj(name,visible);
    //   layer.addToQueryObj(name,visible,queryItem,viz.queryDict);
    //   item.getMap(viz,function(eeLayer){
    //       if(currentGEERunID === geeRunID){
    //         layer.setLayer(eeLayer);
    //         layer.setOpacity();
    //       };
    //      });};

    
    
}

//////////////////////////////////////////////////////
function standardTileURLFunction(url,xThenY,fileExtension,token){
              if(xThenY === null || xThenY === undefined  ){xThenY  = false;};
              if(token === null || token === undefined  ){token  = '';}
              else{token = '?token='+token};
              if(fileExtension === null || fileExtension === undefined  ){fileExtension  = '.png';}
              
              return function(coord, zoom) {
                    // "Wrap" x (logitude) at 180th meridian properly
                    // NB: Don't touch coord.x because coord param is by reference, and changing its x property breakes something in Google's lib 
                    var tilesPerGlobe = 1 << zoom;
                    var x = coord.x % tilesPerGlobe;
                    if (x < 0) {
                        x = tilesPerGlobe+x;
                    }
                    // Wrap y (latitude) in a like manner if you want to enable vertical infinite scroll
                    // return "https://api.mapbox.com/styles/v1/mapbox/satellite-v9/tiles/256/" + zoom + "/" + x + "/" + coord.y + "?access_token=pk.eyJ1IjoiaWhvdXNtYW4iLCJhIjoiY2ltcXQ0cnljMDBwNHZsbTQwYXRtb3FhYiJ9.Sql6G9QR_TQ-OaT5wT6f5Q"
                    if(xThenY ){
                        return url+ zoom + "/" + x + "/" + coord.y +fileExtension+token;
                    }
                    else{return url+ zoom + "/" + coord.y + "/" +x  +fileExtension+token;}//+ (new Date()).getTime();
                    
                }
            }
/////////////////////////////////////////////////////
//Function to add ee object ot map
function addRESTToMap(tileURLFunction,name,visible,maxZoom,helpBox,whichLayerList){
  var viz = {};var item = ee.Image();
  if(whichLayerList === null || whichLayerList === undefined){whichLayerList = "layer-list"}
    // print(item.getInfo().type)
    // if(item.getInfo().type === 'ImageCollection'){print('It is a collection')}
    if(name === null || name === undefined){
        name = "Layer "+NEXT_LAYER_ID;
        
    }

    if(visible === null || visible === undefined){
        visible = true;
    }
    if(maxZoom === null || maxZoom === undefined){
        maxZoom = 18;
    }
    if(helpBox == null){helpBox = ''};
    var layer = document.createElement("REST-layer");
    layer.tileURLFunction = tileURLFunction;
    layer.ID = NEXT_LAYER_ID;
    NEXT_LAYER_ID += 1;
    layer.layerChildID = layerChildID;
    layerChildID++
    layer.name = name ;
    layer.map = map;
    layer.helpBoxMessage = helpBox;
    layer.visible = visible;
    // layer.label = label;
    // layer.fontColor = fontColor;
    layer.helpBox = helpBox;
      layer.maxZoom = maxZoom;
   
    layer.visible = visible;
    layer.item = item;
    layer.name = name;
    
    var layerList = document.querySelector(whichLayerList);
    
    
    layerList.insertBefore(layer,layerList.firstChild);
    layerCount ++;
    item.getMap(viz,function(eeLayer){
        layer.setLayer(eeLayer);
    });
}
//////////////////////////////////////////////////////
function point2LatLng(x,y) {
  
  var m = document.getElementById('map');
  x = x- m.offsetLeft;
  y = y-m.offsetTop;
  // console.log('converting div to lat lng');console.log(x.toString() + ' ' + y.toString());
  var topRight = map.getProjection().fromLatLngToPoint(map.getBounds().getNorthEast());
  var bottomLeft = map.getProjection().fromLatLngToPoint(map.getBounds().getSouthWest());
  var scale = Math.pow(2, map.getZoom());
  var worldPoint = new google.maps.Point(x / scale + bottomLeft.x, y / scale + topRight.y);
  var out = map.getProjection().fromPointToLatLng(worldPoint);
  return out;
}
//////////////////////////////////////////////////////
function getGroundOverlay(baseUrl,minZoom){
  if(map.getZoom()>=minZoom){

  var mapHeight = $('#map').height();
  var mapWidth = $('#map').width();

   var bounds = map.getBounds();
  var keys = Object.keys(bounds);
  var keysX = Object.keys(bounds[keys[0]]);
  var keysY = Object.keys(bounds[keys[1]]);
       // console.log('b');console.log(bounds);
        eeBoundsPoly = ee.Geometry.Rectangle([bounds[keys[1]][keysX[0]],bounds[keys[0]][keysY[0]],bounds[keys[1]][keysX[1]],bounds[keys[0]][keysY[1]]]);

  var ulxy = [bounds[keys[1]][keysX[0]],bounds[keys[0]][keysY[0]]];
  var lrxy = [bounds[keys[1]][keysX[1]],bounds[keys[0]][keysY[1]]];
  var ulxyMercator = llToNAD83(ulxy[0],ulxy[1]);
  var lrxyMercator = llToNAD83(lrxy[0],lrxy[1]);
  
  var url = baseUrl+
  
  ulxyMercator.x.toString()+'%2C'+lrxyMercator.y.toString()+
  '%2C'+
  
  
  lrxyMercator.x.toString()+'%2C'+ulxyMercator.y.toString()+
  '&bboxSR=3857&imageSR=3857&size='+mapWidth.toString()+'%2C'+mapHeight.toString()+'&f=image'

  // console.log('url '+url)
  overlay = new google.maps.GroundOverlay(url,bounds);
  return overlay
}
else{
  url = '../images/blank.png';
  overlay = new google.maps.GroundOverlay(url,map.getBounds())
  return overlay
}
}
//////////////////////////////////////////////////////
/////////////////////////////////////////////////////
//Function to add dynamic object mapping service to map
function addDynamicToMap(baseUrl1,baseUrl2, minZoom1,minZoom2,name,visible,helpBox,whichLayerList){
  if(whichLayerList === null || whichLayerList === undefined){whichLayerList = "layer-list"}
var viz = {};var item = ee.Image();
    // print(item.getInfo().type)
    // if(item.getInfo().type === 'ImageCollection'){print('It is a collection')}
    if(name === null || name === undefined){
        name = "Layer "+NEXT_LAYER_ID;
        
    }

    if(visible === null || visible === undefined){
        visible = true;
    }
    // if(minZoom === null || minZoom === undefined){
    //     minZoom = 8;
    // }
    if(helpBox == null){helpBox = ''};
    function groundOverlayWrapper(){
      if(map.getZoom() > minZoom2){
        return getGroundOverlay(baseUrl2,minZoom2)
      }
      else{
        return getGroundOverlay(baseUrl1,minZoom1)
      }
      }
    var layer = document.createElement("dynamic-layer");
    
    layer.ID = NEXT_LAYER_ID;
    NEXT_LAYER_ID += 1;
    layer.layerChildID = layerChildID;
    layerChildID++
    layer.name = name ;
    layer.map = map;
    layer.helpBoxMessage = helpBox;
    layer.visible = visible;
    layer.groundOverlayFunction = groundOverlayWrapper;
    layer.helpBox = helpBox;
     
   // layer.baseUrl = baseUrl;
    layer.visible = visible;
    layer.item = item;
    layer.name = name;
    
    var layerList = document.querySelector(whichLayerList);
    
    
    layerList.insertBefore(layer,layerList.firstChild);
    layerCount ++;
    layer.startUp();
   
}
function addFeatureToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem){
  console.log('adding feature: '+name);
  item.evaluate(function(v){
    var layer = new google.maps.Data({fillOpacity: 0,strokeColor:'#F00'});
    layer.addGeoJson(v);
    
   
    layer.setMap(map);
    // map.overlayMapTypes.setAt(this.layerId, v);
  })
}
//////////////////////////////////////////////////////
//Function for adding ee object to map
//Will handle vectors by converting them to rasters
// function addToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem){
//     if(canAddToMap){
//     // try{var t = item.bandNames();
        
//         // addRasterToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem);
//       // }
//     // catch(err){
//         // try{
//         // item = ee.Image().paint(item,3,3);
//         addGEEToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem)
//         // addToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList)
//       // }
//     // catch(err){
//     //   item = ee.Image().paint(ee.FeatureCollection([item]),3,3);
//     //     addToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList)
//     // }
//     // };
// }
    
// }
function mp(){
  this.addLayer = function(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem){
    addToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem);
  };
  this.addSerializedLayer = function(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem){
    viz.serialized = true;
    addToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem);
  };
  this.addSelectLayer = function(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem){
    addSelectLayerToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem);
    
  };
  this.addTimeLapse = function(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem){
    addTimeLapseToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem);
  };
  this.addSerializedTimeLapse = function(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem){
    viz.serialized = true;
    addTimeLapseToMap(item,viz,name,visible,label,fontColor,helpBox,whichLayerList,queryItem);
  };
  this.addREST = function(tileURLFunction,name,visible,maxZoom,helpBox,whichLayerList){
    addRESTToMap(tileURLFunction,name,visible,maxZoom,helpBox,whichLayerList);
  };
  this.addExport = function(eeImage,name,res,resMin,resMax,resStep,Export,vizParams){
    addExport(eeImage,name,res,resMin,resMax,resStep,Export,vizParams);
  };
  this.addPlot = function(nameLngLat){
    addPlot(nameLngLat);
  }
  this.centerObject = function(fc){
    centerObject(fc);
  }
}
var Map2 = new mp();

function sleep(delay) {
        var start = new Date().getTime();
        while (new Date().getTime() < start + delay);
      }
function stringToBoolean(string){
    switch(string.toLowerCase().trim()){
        case "true": case "yes": case "1": return true;
        case "false": case "no": case "0": case null: return false;
        default: return Boolean(string);
    }
}
function setGEERunID(){
  geeRunID = new Date().getTime();
}
// function refreshLayerToMap()
function reRun(){
  $('#summary-spinner').show();
  setGEERunID();
  clearSelectedAreas();

  layerChildID = 0;
  geeTileLayersDownloading = 0;
  updateGEETileLayersLoading();

  stopTimeLapse();
  queryObj = {};areaChartCollections = {};pixelChartCollections = {};timeLapseObj = {};
  intervalPeriod = 666.6666666;
  timeLapseID = null;
  timeLapseFrame = 0;
  cumulativeMode = true;

  // if(analysisMode === 'advanced'){
  //   document.getElementById('threshold-container').style.display = 'inline-block';
  //   document.getElementById('advanced-radio-container').style.display = 'inline';
  //   // document.getElementById('charting-container').style.display = 'inline-block';
    
  // }
  // else{
  //   document.getElementById('threshold-container').style.display = 'none';
  //   document.getElementById('advanced-radio-container').style.display = 'none';
  //   // document.getElementById('charting-container').style.display = 'none';
  //   viewBeta = 'no';
  //   lowerThresholdDecline = 0.35;
  //   upperThresholdDecline = 1;
  //   lowerThresholdRecovery = 0.35;
  //   upperThresholdRecovery = 1;
  //   summaryMethod = 'year';
  // }
  clearSelectedAreas();
  selectedFeaturesGeoJSON = {};
  ['layer-list','reference-layer-list','area-charting-select-layer-list','fhp-div','time-lapse-legend-list'].map(function(l){
    $('#'+l).empty();
    $('#legend-'+l).empty();
  })
  
  $('#export-list').empty();
  
	
  Object.values(featureObj).map(function(f){f.setMap(null)});
  featureObj = {};
  map.overlayMapTypes.i.forEach(function(element,index){
                     map.overlayMapTypes.setAt(index,null);
                   
                });

  // map.overlayMapTypes.g = {};
 
    // console.log(layerCount);
    // console.log(refreshNumber);
  
    refreshNumber   ++;
    // layerCount = 0;
  exportImageDict = {};
  clearDownloadDropdown();
  google.maps.event.clearListeners(mapDiv, 'click');
	run();
  // setupFSB();


//     var whileCount = 0;
//     while(whileCount < 5000){
    // while(map.overlayMapTypes.b.length < layerCount*(refreshNumber+1)){}
  //   interval2(function(){
  //     var layerCountN = layerCount;
  //     console.log('cleaning ' +layerCountN.toString());
  //     map.overlayMapTypes.g.slice(0,map.overlayMapTypes.g.length-layerCountN).forEach(function(element,index){
                    
  //                   // if(element !== undefined && element !== null){
  //                   //     console.log('remooooooving');
  //                   // console.log(index);
  //                   // console.log(element)
  //                   map.overlayMapTypes.setAt(index,null);
  //               // };
                    
  //               });  
  // },5000,5)
    
//     whileCount++;
// }
    // processFeatures(fc);
  $('#summary-spinner').hide(); 
}

// function toggleUnits(){
//   if(metricOrImperial === 'metric'){metricOrImperial = 'imperial'}
//     else{metricOrImperial = 'metric'};
// }
// function toggleAreaUnits(){
  
//   // toggleUnits();
//   updateArea();
  
// }
// function toggleDistanceUnits(){
//   // console.log(value);
//   // toggleUnits();
//   updateDistance();
  
  
// }
function getRandomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}
function padLeft(nr, n, str){
    return Array(n-String(nr).length+1).join(str||'0')+nr;
}
function rgbToHex(r,g,b) {
    return "#"+("00000"+(r<<16|g<<8|b).toString(16)).slice(-6);
}
function invertColor(hex) {
    if (hex.indexOf('#') === 0) {
        hex = hex.slice(1);
    }
    // convert 3-digit hex to 6-digits.
    if (hex.length === 3) {
        hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
    }
    if (hex.length !== 6) {
        throw new Error('Invalid HEX color.');
    }
    // invert color components
    var r = (255 - parseInt(hex.slice(0, 2), 16)).toString(16),
        g = (255 - parseInt(hex.slice(2, 4), 16)).toString(16),
        b = (255 - parseInt(hex.slice(4, 6), 16)).toString(16);
    // pad each with zeros and return
    return '#' + padZero(r) + padZero(g) + padZero(b);
}

function padZero(str, len) {
    len = len || 2;
    var zeros = new Array(len).join('0');
    return (zeros + str).slice(-len);
}
function randomColor(){
  var r = getRandomInt(100, 255);
  var g = getRandomInt(0, 255);
  var b = getRandomInt(0, 50);
  var c = rgbToHex(r,g,b)
  return c
}
var chartColorI = 0;
var chartColorsDict = {
  'standard':['#050','#0A0','#e6194B','#14d4f4'],
  'advanced':['#050','#0A0','#9A6324','#6f6f6f','#e6194B','#14d4f4'],
  'advancedBeta':['#050','#0A0','#9A6324','#6f6f6f','#e6194B','#14d4f4','#808','#f58231'],
  'coreLossGain':['#050','#0A0','#e6194B','#14d4f4'],
  'allLossGain':['#050','#0A0','#e6194B','#808','#f58231','#14d4f4'],
  'test':['#9A6324','#6f6f6f','#e6194B','#14d4f4','#880088','#f58231'],
  'testArea':['#e6194B','#14d4f4','#880088','#f58231'],
  'ancillary':['#cc0066','#660033','#9933ff','#330080','#ff3300','#47d147','#00cc99','#ff9966','#b37700']
  }

var chartColors = chartColorsDict.standard;

// ['#111','#808','#fb9a99','#33a02c','#e31a1c','#fdbf6f','#ff7f00','#cab2d6','#6a3d9a','#b15928'];
function getChartColor(){
  var color = chartColors[chartColorI%chartColors.length]
  chartColorI++;
  return color

}
function randomRGBColor(){
  var r = getRandomInt(100, 225);
  var g = getRandomInt(100, 225);
  var b = getRandomInt(100, 225);
  
  return [r,g,b];
}
function randomColors(n){
  var out = [];
  while(n>0){
    out.push(randomColor());
    n = n-1;
  }
  return out
}
//////////////////////////////////
//Taken from: https://sashat.me/2017/01/11/list-of-20-simple-distinct-colors/
var colorList = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6', '#bcf60c', '#fabebe', '#008080', '#e6beff', '#9a6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#ffd8b1', '#000075', '#808080', '#ffffff', '#000000'];
var colorMod = colorList.length;
function getColor(){
  var currentColor =  colorList[colorMod%colorList.length];
  colorMod++;
  return currentColor
}
//Taken from: https://stackoverflow.com/questions/5560248/programmatically-lighten-or-darken-a-hex-color-or-rgb-and-blend-colors
function LightenDarkenColor(col,amt) {
    var usePound = false;
    if ( col[0] == "#" ) {
        col = col.slice(1);
        usePound = true;
    }

    var num = parseInt(col,16);

    var r = (num >> 16) + amt;

    if ( r > 255 ) r = 255;
    else if  (r < 0) r = 0;

    var b = ((num >> 8) & 0x00FF) + amt;

    if ( b > 255 ) b = 255;
    else if  (b < 0) b = 0;

    var g = (num & 0x0000FF) + amt;

    if ( g > 255 ) g = 255;
    else if  ( g < 0 ) g = 0;

    return (usePound?"#":"") + (g | (b << 8) | (r << 16)).toString(16);
}
function startArea(){
  
  if(polyOn === false){
    // $( "#area-measurement" ).html( 'Click on map to start measuring<br>Press "Delete" or "d" button to clear<br>Press "u" to undo last vertex placement<br>Press "None" radio button to stop measuring');
    polyOn = true;
  }
  // 
   // $( "#distance-area-measurement" ).style.width = '0px';
  // document.getElementById('area-measurement').style.display = 'block';
  // document.getElementById('area-measurement').value = 'a';
  // currentColor =  colorList[colorMod%colorList.length];
    // areaPolygonOptions = {
    //           strokeColor:currentColor,
    //             fillOpacity:0.2,
    //           strokeOpacity: 1,
    //           strokeWeight: 3,
    //           draggable: true,
    //           editable: true,
    //           geodesic:true,
    //           polyNumber: polyNumber
    //         };
        areaPolygonOptions.polyNumber = polyNumber;
        // colorMod++;
    map.setOptions({draggableCursor:'crosshair'});
    map.setOptions({disableDoubleClickZoom: true });

    // Construct the polygon.
        areaPolygonObj[polyNumber] = new google.maps.Polyline(areaPolygonOptions);
        areaPolygonObj[polyNumber].setMap(map);

        // areaPolygon = new google.maps.Polygon(areaPolygonOptions);
        // areaPolygon.setMap(map);

    updateArea = function(){
      var unitName;var unitMultiplier;
        var keys = Object.keys(areaPolygonObj);
        // console.log('keys');console.log(keys);
        var totalArea = 0;
        var totalWithArea = 0;
        var outString = '';
        function areaWrapper(key){
          // console.log('key');console.log(key);
        // print('Adding in: '+key.toString());
        var pathT = areaPolygonObj[key].getPath().j
        if(pathT.length > 0){

          clickCoords =clickLngLat;//pathT[pathT.length-1];
           console.log(clickCoords)
           console.log(pathT)
          // console.log(clickCoords);console.log(pathT.length);
          area = google.maps.geometry.spherical.computeArea(areaPolygonObj[key].getPath());
          
          var unitNames = unitNameDict[metricOrImperialArea].area;
          var unitMultipliers = unitMultiplierDict[metricOrImperialArea].area;
          

          
          // if(area >= 1){
          //   var unitNameT = unitNames[1];
          //   var unitMultiplierT = unitMultipliers[1];
          // }
          // else{
          //   var unitNameT = unitNames[0];
          //   var unitMultiplierT = unitMultipliers[0];
          //   };
          // area = area;//*unitMultiplier
          // console.log(unitName);
          // console.log(unitMultiplier);
          if(area>0){
            totalWithArea++;
            // outString  = outString + area*unitMultiplier.toFixed(4).toString() + ' ' + unitName + '<br>'
          }
          totalArea = totalArea + area

          if(totalArea >= 1000){
            unitName = unitNames[1];
            unitMultiplier = unitMultipliers[1];
          }
          else{
            unitName = unitNames[0];
            unitMultiplier = unitMultipliers[0];
            }
          console.log(unitNames);
          console.log(unitMultipliers);
          console.log(area);
          console.log(totalArea);
          console.log(unitName);
          console.log(unitMultiplier)
        }
        // console.log(totalArea);
      }
      keys.map(areaWrapper)
      var pixelProp = totalArea/9;

      totalArea = totalArea*unitMultiplier;
        // if(infowindow != undefined){infowindow.close()}
        // if(totalArea > 0){
            // infowindow = new google.maps.InfoWindow({
            // content: area.toFixed(2) + unit,
            // position: clickCoords
            // });
            // infowindow.open(map);
             totalArea = totalArea.formatNumber();

          var polyString = 'polygon';
          if(keys.length>1){
            polyString = 'polygons';
          }
          var areaContent = totalWithArea.toString()+' '+polyString+' <br>'+totalArea +' '+unitName ;
          if(mode === 'Ancillary'){areaContent += '<br>'+pixelProp.formatNumber() + ' % pixel'}
          // $( "#area-measurement" ).html(areaContent);//+' <br>' +pixelProp.toFixed(2) + '%pixel');
          infowindow.setContent(areaContent);
          infowindow.setPosition(clickCoords);
          
          infowindow.open(map);
          $('.gm-ui-hover-effect').hide();
          // $('#tool-message-box').empty();
          // $('#tool-message-box').show();
          // $('#tool-message-box').append(areaContent);
          
            // }       
    }
    // function newPoly(){
    //   areaPolygonObj[polyNumber].setMap(null);
    //   areaPolygonObj[polyNumber] = new google.maps.Polygon(areaPolygonOptions);
    //   areaPolygonObj[polyNumber].setMap(map);
    //   google.maps.event.addListener(areaPolygon, 'dblclick', function() {
    //     console.log('doubleClicked');
    //     newPoly();
    //     // resetPolygon();
    // });
    // }
  startListening();
}
function setToPolygon(id){
        if(id == undefined || id == null){id = polyNumber};
        console.log('Setting '+id.toString()+' to polygon');
        areaPolygonOptions.strokeColor = areaPolygonObj[id].strokeColor;
        var path = areaPolygonObj[id].getPath();
        areaPolygonObj[id].setMap(null);
        areaPolygonObj[id] = new google.maps.Polygon(areaPolygonOptions);
        areaPolygonObj[id].setPath(path);
        areaPolygonObj[id].setMap(map);
}
function setToPolyline(id){
        if(id == undefined || id == null){id = polyNumber};
        areaPolygonOptions.strokeColor = areaPolygonObj[id].strokeColor;
        var path = areaPolygonObj[polyNumber].getPath();
        areaPolygonObj[id].setMap(null);
        areaPolygonObj[id] = new google.maps.Polyline(areaPolygonOptions);
        areaPolygonObj[id].setPath(path);
        areaPolygonObj[id].setMap(map);
}


function startListening(){
    // google.maps.event.addDomListener(map, 'click', function(event) {
    //     // console.log(event)
    //     // var path = areaPolygonObj[polyNumber].getPath();
    //     // path.push(event.latLng);
    //     // updateArea();
    //     console.log(event.latLng)
   
    
    // });
    // google.maps.event.addDomListener(mapDiv, 'click', function(event) {
        
        

    //     var path = areaPolygonObj[polyNumber].getPath();
    //     var x =event.clientX;
    //     var y = event.clientY;
    //     clickLngLat =point2LatLng(x,y)
    //     path.push(clickLngLat);
    //     updateArea();
    
    // });
    // google.maps.event.addDomListener(mapDiv, 'dblclick', function() {
    mapHammer = new Hammer(document.getElementById('map'));

    mapHammer.on("tap", function(event) {
        

        var path = areaPolygonObj[polyNumber].getPath();
        var x =event.center.x;
        var y = event.center.y;
        clickLngLat =point2LatLng(x,y);
        // udpList.push([clickLngLat.lng(),clickLngLat.lat()])
        path.push(clickLngLat);
        updateArea();
    
    });
    mapHammer.on("doubletap",function(){
        // console.log('doubleClicked');
        // newPoly();
        // startArea();
        
   
        
        setToPolygon()
        
        resetPolygon();

    });


    // var thisPoly = areaPolygonObj[polyNumber]
    // if(thisPoly.getPath().length > 2){
      // google.maps.event.addListener(thisPoly, "click", function(){activatePoly(thisPoly)});
    // }
    google.maps.event.addListener(areaPolygonObj[polyNumber], "click", updateArea);
 
    google.maps.event.addListener(areaPolygonObj[polyNumber], "mouseup", updateArea);
    google.maps.event.addListener(areaPolygonObj[polyNumber], "dragend", updateArea);
    google.maps.event.addListener(areaPolygonObj[polyNumber].getPath(), 'set_at',  updateArea);

    window.addEventListener("keydown", resetPolys);
    window.addEventListener("keydown", deleteLastAreaVertex);

}
function resetPolys(e){
 
     
      if( e === undefined || e.key === 'Delete'|| e.key === 'd'|| e.key === 'Backspace' ){
        stopArea();
        startArea();
      }
    }
function undoAreaMeasuring(){
  if(areaPolygonObj[polyNumber].getPath().length >0){
          areaPolygonObj[polyNumber].getPath().pop(1);
          updateArea();
        }

        else if(polyNumber > 1){
          stopListening();
          polyNumber = polyNumber -1;
          setToPolyline()
          startListening();
        }
}
function undoDistanceMeasuring(){
  distancePolyline.getPath().pop(1);
  updateDistance();
}
function deleteLastAreaVertex(e){
      // console.log(e);
      if(e.key == 'z' && e.ctrlKey){
        undoAreaMeasuring();
      }
    }
function deleteLastDistanceVertex(e){
      // console.log(e);
      if(e.key == 'z' && e.ctrlKey){
        undoDistanceMeasuring();
      }
    }
function activatePoly(poly){
  // stopListening();
  // var keys = Object.keys(areaPolygonObj);
  // keys.map(function(k){
  //   setToPolygon(k)
  //   areaPolygonObj[k].setEditable(false);
  //   areaPolygonObj[k].setDraggable(false);
    

  // })
  // polyNumber = poly.polyNumber;
  // areaPolygonObj[poly.polyNumber].setEditable(true);
  // areaPolygonObj[poly.polyNumber].setDraggable(true);
  // setToPolyline()
  // startListening();
 
 
  
  console.log(poly.polyNumber)
}
function stopListening(){
    // areaPolygonObj[polyNumber].setEditable(false);
    // areaPolygonObj[polyNumber].setDraggable(false);
    try{
    mapHammer.destroy();
    // console.log(areaPolygonObj[polyNumber].polyNumber);
    google.maps.event.clearListeners(areaPolygonObj[polyNumber], 'dblclick');
    google.maps.event.clearListeners(areaPolygonObj[polyNumber], 'click');
    google.maps.event.clearListeners(mapDiv, 'click');
    google.maps.event.clearListeners(areaPolygonObj[polyNumber], 'mouseup');
    google.maps.event.clearListeners(areaPolygonObj[polyNumber], 'dragend');
    // if(infowindow != undefined){infowindow.close()}
    window.removeEventListener('keydown',resetPolys);
    window.removeEventListener('keydown',deleteLastAreaVertex);
    // var thisPoly = areaPolygonObj[polyNumber]
    // if(thisPoly.getPath().length > 2){
    //   google.maps.event.addListener(thisPoly, "click", function(){activatePoly(thisPoly)});
    // }
    }catch(err){}
    
    
}
function clearPoly(id){

  areaPolygonObj[id].setMap(null);
  areaPolygonObj[id].setPath([]);
  updateArea();
  google.maps.event.clearListeners(areaPolygonObj[id], 'click');
}
function clearPolys(){
  stopListening();
  var keys = Object.keys(areaPolygonObj);
  keys.map(function(k){areaPolygonObj[k].setMap(null);})
  areaPolygonObj = {};
  polyNumber = 1;
  polyOn = false;

}
function stopArea(){
  // google.maps.event.clearListeners(mapDiv, 'dblclick');
  try{
    mapHammer.destroy();
  }catch(err){}
  
    // google.maps.event.clearListeners(mapDiv, 'click');
  // $( "#area-measurement" ).html( '');
  // document.getElementById('area-measurement').style.display = 'none';
  map.setOptions({disableDoubleClickZoom: true });
  
  clearPolys();
  infowindow.setMap(null);
  map.setOptions({draggableCursor:'hand'});
   // $('#tool-message-box').empty();
    // $('#tool-message-box').hide();
  // map.setOptions({draggableCursor:'hand'});
  
}
//
function resetPolygon(){
    stopListening();
    var keys = Object.keys(areaPolygonObj);
    var lastKey = keys[keys.length-1];
    console.log('last key '+lastKey.toString());
    polyNumber = parseInt(lastKey);
    polyNumber++;
    startArea();
    // console.log(areaPolygonObj)
}
function newPolygon(){
  stopArea();

}
///////////////////////////////////////////////////////////////////////////////////
function startDistance(){
  // showTip("DISTANCE MEASURING","Click on map to measure distance. Double click on map to clear")
  // $( "#distance-measurement" ).html( 'Click on map to start measuring<br>Double click to finish measurement');
  
  // document.getElementById('distance-measurement').style.display = 'inline-block';
  // document.getElementById('distance-measurement').value = 'd';
    
    map.setOptions({draggableCursor:'crosshair'});
    // console.log(distancePolylineOptions);
    try{
      distancePolyline.destroy();
    }catch(err){};
    
    distancePolyline = new google.maps.Polyline(distancePolylineOptions);
    distancePolyline.setMap(map);


    


    map.setOptions({disableDoubleClickZoom: true });



    google.maps.event.addListener(distancePolyline, "click", updateDistance);
    mapHammer = new Hammer(document.getElementById('map'));
    mapHammer.on("doubletap", resetPolyline);
    mapHammer.on("tap", function(event) {
        // console.log('clicked');
        var x =event.center.x;
        var y = event.center.y;
        var path = distancePolyline.getPath();
        clickLngLat =point2LatLng(x,y)
        path.push(clickLngLat);
        updateDistance();
    });
    // google.maps.event.addDomListener(mapDiv, "dblclick", resetPolyline);
    google.maps.event.addListener(distancePolyline, "mouseup", updateDistance);
    google.maps.event.addListener(distancePolyline, "dragend", updateDistance);
    google.maps.event.addListener(distancePolyline.getPath(), 'set_at',  updateDistance);
    window.addEventListener('keydown',deleteLastDistanceVertex);
    window.addEventListener('keydown',resetPolyline);
    // distanceUpdater = setInterval(function(){updateMarkerPositionList();updateDistance();},500);

    }

function stopDistance(){
  // $( "#distance-measurement" ).html( '');
  // document.getElementById('distance-measurement').style.display = 'none';
  try{
    window.removeEventListener('keydown',deleteLastDistanceVertex);
    window.removeEventListener('keydown',resetPolyline);
    mapHammer.destroy();
    map.setOptions({disableDoubleClickZoom: true });
    // google.maps.event.clearListeners(mapDiv, 'dblclick');
    google.maps.event.clearListeners(distancePolyline, 'click');
    google.maps.event.clearListeners(mapDiv, 'click');
    google.maps.event.clearListeners(distancePolyline, 'mouseup');
    google.maps.event.clearListeners(distancePolyline, 'dragend');
    if(infowindow != undefined){infowindow.setMap(null);}
    distancePolyline.setMap(null);
    // clearInterval(distanceUpdater);
    map.setOptions({draggableCursor:'hand'});
    infowindow.setMap(null);
    // $('#tool-message-box').empty();
    // $('#tool-message-box').hide();
  }catch(err){}
    
}

function resetPolyline(e){
  // console.log(e.key);
  if(e === undefined || e.key === undefined ||  e.key == 'Delete'|| e.key == 'd'|| e.key == 'Backspace'){
    stopDistance();startDistance();
  }    
}
    
// function updateMarkerPositionList(){
//     var distance = google.maps.geometry.spherical.computeLength(distancePolyline.getPath());
//     console.log(distance);
//     var pathT = distancePolyline.getPath().b
//     markerPositionList = pathT.map(function(xy){return [xy.lat(),xy.lng()]})
//     clickCoords = distancePolyline.getPath().b[pathT.length-1]
// }
updateDistance = function(){
    distance = google.maps.geometry.spherical.computeLength(distancePolyline.getPath());
    var pathT = distancePolyline.getPath().j;
    clickCoords = clickLngLat;//pathT[pathT.length-1];
    // console.log(clickCoords)
    
    var unitNames = unitNameDict[metricOrImperialDistance].distance;
    var unitMultipliers = unitMultiplierDict[metricOrImperialDistance].distance;
    // console.log(unitNames);
    // console.log(unitMultipliers);
    // console.log(area)
        
    if(distance >= 1000){
      var unitName = unitNames[1];
      var unitMultiplier = unitMultipliers[1];
    }
    else{
      var unitName = unitNames[0];
      var unitMultiplier = unitMultipliers[0];
      }
    distance = distance*unitMultiplier
    // console.log(unitName);
    // console.log(unitMultiplier);

    if(distance >= 0){
     
          var distanceContent = distance.formatNumber() + ' ' + unitName 
          // $( "#distance-measurement" ).html(distanceContent);
    
          infowindow.setContent(distanceContent);
          infowindow.setPosition(clickCoords);

          infowindow.open(map);
          // $('#tool-message-box').empty();
          // $('#tool-message-box').show();
          // $('#tool-message-box').append(distanceContent);
          $('.gm-ui-hover-effect').hide();


    }

}
function getDistance(lat1,lon1,lat2,lon2){
    var R = 6371e3; // metres
    var phi1 = lat1* Math.PI / 180;
    var phi2 = lat2* Math.PI / 180;
    var deltaPhi = (lat2-lat1)* Math.PI / 180;
    var deltaLambda = (lon2-lon1)* Math.PI / 180;

    var a = Math.sin(deltaPhi/2) * Math.sin(deltaPhi/2) +
            Math.cos(phi1) * Math.cos(phi2) *
            Math.sin(deltaLambda/2) * Math.sin(deltaLambda/2);
    var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));

    var d = R * c;
    return d
}


function addFusionTable1(id){
var layer1 = new google.maps.FusionTablesLayer({
          query: {
            select: 'geometry',
            from: id
          },
          styles: [{
      polygonOptions: {
        // fillColor: '#00FF00',
        fillOpacity: 0.0000000000001,
        strokeColor:'#FF0000',
        strokeWeight : 2
      }
    }]
    // map:map
        });
    layer1.setMap(map);
    }
function addFusionTable2(id){
var layer2 = new google.maps.FusionTablesLayer({
          query: {
            select: 'geometry',
            from: id
          },
          styles: [{
      polygonOptions: {
        // fillColor: '#00FF00',
        fillOpacity: 0.0000000000001,
        strokeColor:'#FF0000',
        strokeWeight : 2
      }
    }]
        });
layer2.setMap(map);
    
    }



function dropdownUpdateStudyArea(whichOne){
  $('#summary-spinner').show();
   
  resetStudyArea(whichOne);

   // localStorage.setItem("cachedStudyAreaName",this.innerHTML)
   //  $('.status').text(this.innerHTML);
   //  $('#study-area-label').text(this.innerHTML);
    var coords = studyAreaDict[whichOne].center;

    // studyAreaName = studyAreaDict[this.innerHTML][0];
   //  // exportCRS = studyAreaDict[this.innerHTML][2];
   //  // $('input[name = "Export crs"]').val(exportCRS);
    centerMap(coords[1],coords[0],coords[2]);
    if(mode === 'Ancillary'){
      run = runSimple;
    } else if( mode === 'LT'){
      run  = runLT;
    }else if(mode === 'lcms-base-learner'){
      run = runBaseLearner
    }
      else if(studyAreaName === 'CONUS'){
      run = runCONUS
    }else{run = runUSFS};

    
    

    reRun();
    // $('#summary-spinner').hide();
};
var resetStudyArea = function(whichOne){

    localStorage.setItem("cachedStudyAreaName",whichOne)
   
    $('#studyAreaDropdown').val(whichOne);
    $('#study-area-label').text(whichOne);
    console.log('changing study area');
    console.log(whichOne);
    lowerThresholdDecline =  studyAreaDict[whichOne].lossThresh;
    if(studyAreaDict[whichOne].lossSlowThresh !== undefined  && studyAreaDict[whichOne].lossSlowThresh !== null){
      lowerThresholdSlowLoss = studyAreaDict[whichOne].lossSlowThresh;
    }else{
      lowerThresholdSlowLoss = lowerThresholdDecline;
    }
    if(studyAreaDict[whichOne].lossFastThresh !== undefined  && studyAreaDict[whichOne].lossFastThresh !== null){
      lowerThresholdFastLoss = studyAreaDict[whichOne].lossFastThresh;
    }else{
      lowerThresholdFastLoss = lowerThresholdDecline;
    }
   
    upperThresholdDecline = 1;
    upperThresholdSlowLoss = 1;
    upperThresholdFastLoss = 1;
    lowerThresholdRecovery = studyAreaDict[whichOne].gainThresh;
    upperThresholdRecovery = 1;
    
    startYear = studyAreaDict[whichOne].startYear;
    endYear = studyAreaDict[whichOne].endYear;
   
    setUpRangeSlider('lowerThresholdDecline',0,1,lowerThresholdDecline,0.05,'decline-threshold-slider','null');
    setUpRangeSlider('lowerThresholdRecovery',0,1,lowerThresholdRecovery,0.05,'recovery-threshold-slider','null');
    
    setUpRangeSlider('lowerThresholdSlowLoss',0,1,lowerThresholdSlowLoss,0.05,'slow-loss-threshold-slider','null');
    setUpRangeSlider('lowerThresholdFastLoss',0,1,lowerThresholdFastLoss,0.05,'fast-loss-threshold-slider','null');
    
    setUpDualRangeSlider('startYear','endYear',startYear,endYear,startYear,endYear,1,'analysis-year-slider','analysis-year-slider-update','null')
    

    var coords = studyAreaDict[whichOne].center;
    studyAreaName = studyAreaDict[whichOne].name;
    if(studyAreaName === 'CONUS'){run = runCONUS;}
    else{run = runUSFS;};
    // console.log(studyAreaDict[whichOne].addFastSlow)
    if(studyAreaDict[whichOne].addFastSlow){
      $('#fast-slow-threshold-container').show();
    }else{$('#fast-slow-threshold-container').hide();}
    if(studyAreaDict[whichOne].addGainThresh){
      $('#recovery-threshold-slider-container').show();
    }else{$('#recovery-threshold-slider-container').hide();}
    $('#export-crs').val(studyAreaDict[whichOne].crs)
    // exportCRS = studyAreaDict[whichOne][2];
    // $('#export-crs').val(exportCRS);
    // centerMap(coords[1],coords[0],8);
    // reRun();

}
function initSearchBox() {
     

        // Create the search box and link it to the UI element.
        var input = document.getElementById('pac-input');
        var searchBox = new google.maps.places.SearchBox(input);
        // map.controls[google.maps.ControlPosition.TOP_LEFT].push(input);

        // Bias the SearchBox results towards current map's viewport.
        map.addListener('bounds_changed', function() {
          searchBox.setBounds(map.getBounds());
        });

        var markers = [];
        // Listen for the event fired when the user selects a prediction and retrieve
        // more details for that place.
        searchBox.addListener('places_changed', function() {
          var places = searchBox.getPlaces();

          if (places.length == 0) {
            return;
          }

          // Clear out the old markers.
          markers.forEach(function(marker) {
            marker.setMap(null);
          });
          markers = [];

          // For each place, get the icon, name and location.
          var bounds = new google.maps.LatLngBounds();
          places.forEach(function(place) {
            if (!place.geometry) {
              console.log("Returned place contains no geometry");
              return;
            }
            var icon = {
              url: place.icon,
              size: new google.maps.Size(71, 71),
              origin: new google.maps.Point(0, 0),
              anchor: new google.maps.Point(17, 34),
              scaledSize: new google.maps.Size(25, 25)
            };

            // Create a marker for each place.
            markers.push(new google.maps.Marker({
              map: map,
              icon: icon,
              title: place.name,
              position: place.geometry.location
            }));

            if (place.geometry.viewport) {
              // Only geocodes have viewport.
              bounds.union(place.geometry.viewport);
            } else {
              bounds.extend(place.geometry.location);
            }
          });
          map.fitBounds(bounds);
        });
      }
var infoWindowXOffset = 30;

function getInfoWindow(xOffset,yOffset){
  if(xOffset == null || xOffset === undefined){xOffset = 30};
  if(yOffset == null || yOffset === undefined){yOffset = -30};
  return new google.maps.InfoWindow({
    content : '',
    maxWidth: 300,
    pixelOffset: new google.maps.Size(xOffset,yOffset,'rem','rem'),
    close:false
  });
} 
function initialize() {
  // Create a new StyledMapType object, passing it an array of styles,
        // and the name to be displayed on the map type control.
        var styledMapType = new google.maps.StyledMapType(
            [
  {
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#212121"
      }
    ]
  },
  {
    "elementType": "labels.icon",
    "stylers": [
      {
        "visibility": "off"
      }
    ]
  },
  {
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#757575"
      }
    ]
  },
  {
    "elementType": "labels.text.stroke",
    "stylers": [
      {
        "color": "#212121"
      }
    ]
  },
  {
    "featureType": "administrative",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#757575"
      }
    ]
  },
  {
    "featureType": "administrative.country",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#9e9e9e"
      }
    ]
  },
  {
    "featureType": "administrative.land_parcel",
    "stylers": [
      {
        "visibility": "off"
      }
    ]
  },
  {
    "featureType": "administrative.locality",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#bdbdbd"
      }
    ]
  },
  {
    "featureType": "poi",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#757575"
      }
    ]
  },
  {
    "featureType": "poi.park",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#181818"
      }
    ]
  },
  {
    "featureType": "poi.park",
    "elementType": "geometry.fill",
    "stylers": [
      {
        "color": "#004000"
      }
    ]
  },
  {
    "featureType": "poi.park",
    "elementType": "labels.icon",
    "stylers": [
      {
        "color": "#004000"
      }
    ]
  },
  {
    "featureType": "poi.park",
    "elementType": "labels.text",
    "stylers": [
      {
        "color": "#004000"
      }
    ]
  },
  {
    "featureType": "poi.park",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#616161"
      }
    ]
  },
  {
    "featureType": "poi.park",
    "elementType": "labels.text.stroke",
    "stylers": [
      {
        "color": "#1b1b1b"
      }
    ]
  },
  {
    "featureType": "road",
    "elementType": "geometry.fill",
    "stylers": [
      {
        "color": "#2c2c2c"
      }
    ]
  },
  {
    "featureType": "road",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#8a8a8a"
      }
    ]
  },
  {
    "featureType": "road.arterial",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#373737"
      }
    ]
  },
  {
    "featureType": "road.highway",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#3c3c3c"
      }
    ]
  },
  {
    "featureType": "road.highway.controlled_access",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#4e4e4e"
      }
    ]
  },
  {
    "featureType": "road.local",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#616161"
      }
    ]
  },
  {
    "featureType": "transit",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#757575"
      }
    ]
  },
  {
    "featureType": "water",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#000000"
      }
    ]
  },
  {
    "featureType": "water",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#3d3d3d"
      }
    ]
  }
],
            {name: 'Dark Mode'});

     
  var mapOptions = {
    center: null,
    zoom: null,
    minZoom: 2,
    // gestureHandling: 'greedy',
    disableDoubleClickZoom: true,
    // maxZoom: 15,
    mapTypeId: google.maps.MapTypeId.HYBRID,
    streetViewControl: true,
    fullscreenControl: false,
    mapTypeControlOptions :{position: google.maps.ControlPosition.TOP_RIGHT,mapTypeIds: ['roadmap', 'satellite', 'hybrid', 'terrain',
                    'dark_mode']},
    // fullscreenControlOptions:{position: google.maps.ControlPosition.RIGHT_TOP},
    streetViewControlOptions:{position: google.maps.ControlPosition.RIGHT_TOP},
    scaleControlOptions:{position: google.maps.ControlPosition.RIGHT_TOP},
    zoomControlOptions:{position: google.maps.ControlPosition.RIGHT_TOP},
    tilt:0,
    controlSize: 25,
    scaleControl: true,
    clickableIcons:false,
  };
   

       
  // console.log(initialCenter)
  var center = new google.maps.LatLng(initialCenter[0],initialCenter[1]);
  var zoom = initialZoomLevel;//8;

  var settings = null;


  // var randomID = null;
  if(typeof(Storage) !== "undefined"){
    cachedStudyAreaName = localStorage.getItem("cachedStudyAreaName");
    if(cachedStudyAreaName === null || cachedStudyAreaName === undefined){
      cachedStudyAreaName = defaultStudyArea;
    }
    studyAreaName = studyAreaDict[cachedStudyAreaName].name;
    longStudyAreaName = cachedStudyAreaName;
    $('#study-area-label').text(longStudyAreaName);
    $('#study-area-label').fitText(1.8);
    
    if(studyAreaSpecificPage == true){
      cachedSettingskey =  studyAreaName +"-settings";
      
    }
    settings = JSON.parse(localStorage.getItem(cachedSettingskey));
    
    layerObj =  null;//JSON.parse(localStorage.getItem("layerObj"));
    
  }

  if(settings != null && settings.center != null && settings.zoom != null){
    center = settings.center;
    zoom  = settings.zoom;
  }
  if(layerObj === null){
    layerObj = {};
  }

 

	 // console.log(center);console.log(zoom);
    mapOptions.center = center;
    mapOptions.zoom = zoom;
     
    map = new google.maps.Map(document.getElementById("map"),
                                  mapOptions);
     //Associate the styled map with the MapTypeId and set it to display.
    map.mapTypes.set('dark_mode', styledMapType);
        
    marker=new google.maps.Circle({
    center:{lat:45,lng:-111},
    radius:5
  });
  
  infowindow = getInfoWindow();

  queryGeoJSON = new google.maps.Data();
  queryGeoJSON.setMap(map);
  queryGeoJSON.setStyle({strokeColor:'#FF0'});
    initSearchBox();
    
       
   //  var testUrl = 'https://ecos.fws.gov/arcgis/rest/services/cap/cap/MapServer/0?f=pjson'
   // var ctaLayer = new google.maps.KmlLayer({
   //        url: '../layers/change_no_change_shp2_k.kml',
   //        map: map
   //      });
            placeholderID = 1;


            function addWMS(url,name,maxZoom,xThenY){
              if(maxZoom === null || maxZoom === undefined  ){
                maxZoom = 19;
              }
              if(xThenY === null || xThenY === undefined  ){
                xThenY = false;
              }
                var imageMapType =  new google.maps.ImageMapType({
                getTileUrl: function(coord, zoom) {
                    // "Wrap" x (logitude) at 180th meridian properly
                    // NB: Don't touch coord.x because coord param is by reference, and changing its x property breakes something in Google's lib 
                    var tilesPerGlobe = 1 << zoom;
                    var x = coord.x % tilesPerGlobe;
                    if (x < 0) {
                        x = tilesPerGlobe+x;
                    }
                    // Wrap y (latitude) in a like manner if you want to enable vertical infinite scroll
                    // return "https://api.mapbox.com/styles/v1/mapbox/satellite-v9/tiles/256/" + zoom + "/" + x + "/" + coord.y + "?access_token=pk.eyJ1IjoiaWhvdXNtYW4iLCJhIjoiY2ltcXQ0cnljMDBwNHZsbTQwYXRtb3FhYiJ9.Sql6G9QR_TQ-OaT5wT6f5Q"
                    if(xThenY ){
                        return url+ zoom + "/" + x + "/" + coord.y +".png?";
                    }
                    else{return url+ zoom + "/" + coord.y + "/" +x  +".png?";}//+ (new Date()).getTime();
                    
                },
                tileSize: new google.maps.Size(256, 256),
                name: name,
                maxZoom: maxZoom
            
            })

                   
                map.mapTypes.set('Placeholder' + placeholderID.toString(),imageMapType )
                placeholderID  ++;
            }
              

        
        var zoomDict = {20 : '1,128.49',
                        19 : '2,256.99',
                        18 : '4,513.98',
                        17 : '9,027.97',
                        16 : '18,055.95',
                        15 : '36,111.91',
                        14 : '72,223.82',
                        13 : '144,447.64',
                        12 : '288,895.28',
                        11 : '577,790.57',
                        10 : '1,155,581.15',
                        9  : '2,311,162.30',
                        8  : '4,622,324.61',
                        7  : '9,244,649.22',
                        6  : '18,489,298.45',
                        5  : '36,978,596.91',
                        4  : '73,957,193.82',
                        3  : '147,914,387.60',
                        2  : '295,828,775.30',
                        1  : '591,657,550.50'}

        
        function updateMousePositionAndZoom(cLng,cLat,zoom,elevation){
                $('.legendDiv').css('bottom',$('.bottombar').height());
                $( "#current-mouse-position" ).html( 'Lng: ' +cLng + ', Lat: ' + cLat +', '+elevation+ 'Zoom: ' +zoom +', 1:'+zoomDict[zoom]);
        }
        
        // var elevationAPIKey = 'AIzaSyBiTunmJOy6JFGYWy2ms4_ScCOqK4rFf3w';
        // var elevationAPIKey = 'AIzaSyCXwPx9_pOQsvd-b_bG8ueGI82JnJO2mess';
        var elevator = new google.maps.ElevationService;
        var lastElevation = 0;
        var elevationCheckTime = 0
        function getElevation(center){
        mouseLat = center.lat().toFixed(4).toString();
        elevator.getElevationForLocations({
        'locations': [center]
        }, function(results, status) {
            // console.log(status);
        if(status === 'OVER_QUERY_LIMIT'){
          lastElevation = '';
          updateMousePositionAndZoom(mouseLng,mouseLat,zoom,'');
        }
        else if (status === 'OK') {
          // Retrieve the first result
          if (results[0]) {
            // Open the infowindow indicating the elevation at the clicked position.
                var thisElevation = results[0].elevation.toFixed(1);
                var thisElevationFt = (thisElevation*3.28084).toFixed(1);
                lastElevation = 'Elevation: '+thisElevation.toString()+'(m),'+thisElevationFt.toString()+'(ft),';
                updateMousePositionAndZoom(mouseLng,mouseLat,zoom,lastElevation)
                
          } else {
            updateMousePositionAndZoom(mouseLng,mouseLat,zoom,'No results found');
          }
        } 
        else {
          updateMousePositionAndZoom(mouseLng,mouseLat,zoom,lastElevation);
        }
        });
        }
        google.maps.event.addDomListener(mapDiv,'mousemove',function(event){
            var x =event.clientX;
            var y = event.clientY;
            var center =point2LatLng(x,y);
            var zoom = map.getZoom();
            // var center = event.latLng;
            mouseLat = center.lat().toFixed(4).toString();
            mouseLng = center.lng().toFixed(4).toString();
            var now = new Date().getTime()
            var dt = now - elevationCheckTime  ;
            
            if(dt > 2000){
              getElevation(center);
              elevationCheckTime = now;
            }
            else{updateMousePositionAndZoom(mouseLng,mouseLat,zoom,lastElevation)}
            
        })
        google.maps.event.addListener(map,'zoom_changed',function(){
            var zoom = map.getZoom();
            
            console.log('zoom changed')
            
            updateMousePositionAndZoom(mouseLng,mouseLat,zoom,lastElevation)
        })

    google.maps.event.addListener(map,'bounds_changed',function(){
      zoom = map.getZoom();
      // console.log('bounds changed');
      var bounds = map.getBounds();
      var keys = Object.keys(bounds);
      var keysX = Object.keys(bounds[keys[0]]);
      var keysY = Object.keys(bounds[keys[1]]);
      // console.log('b');console.log(bounds);
      eeBoundsPoly = ee.Geometry.Rectangle([bounds[keys[1]][keysX[0]],bounds[keys[0]][keysY[0]],bounds[keys[1]][keysX[1]],bounds[keys[0]][keysY[1]]]);

        if(typeof(Storage) == "undefined") return;
        
        localStorage.setItem(cachedSettingskey,JSON.stringify({center:{lat:map.getCenter().lat(),lng:map.getCenter().lng()},zoom:map.getZoom()}));
    });

    
    
        
    // if(randomID === null){randomID = parseInt(Math.random()*1000000)}
    // localStorage.setItem("randomID",JSON.stringify(randomID));

    //Specify proxy server location
    //Proxy server used for EE and GCS auth
    //RCR appspot proxy costs $$
	// ee.initialize("https://rcr-ee-proxy-server2.appspot.com/api","https://earthengine.googleapis.com/map",function(){
    ee.initialize(authProxyAPIURL,geeAPIURL,function(){
    
    // ee.initialize("http://localhost:8080/api","https://earthengine.googleapis.com/map",function(){
    if(cachedStudyAreaName === null){
      $('#study-area-label').text(defaultStudyArea);
    }
    if(mode === 'Ancillary'){
      run = runSimple;
    } else if( mode === 'LT'){
      run  = runLT;
    } else if(mode === 'MTBS'){
      run = runMTBS;
    }else if(mode === 'TEST'){
      run = runTest;
    }else if(mode === 'FHP'){
      run = runFHP;
    }else if(mode === 'geeViz'){
      run = runGeeViz;
    }else if(mode === 'lcms-base-learner'){
      run = runBaseLearner
    }else if(studyAreaName === 'CONUS'){
      longStudyAreaName = cachedStudyAreaName;
      run = runCONUS;
    
    }else if(cachedStudyAreaName != null){
      longStudyAreaName = cachedStudyAreaName;
      resetStudyArea(cachedStudyAreaName)
    } 
    else{run = runUSFS}

   
  setGEERunID();
  run();
  // setupFSB();

  if(plotsOn){
    addPlotCollapse();
    loadAllPlots();
  }
  
  $('#summary-spinner').hide();
  if(localStorage.showIntroModal === 'true'){
    $('#introModal').modal().show();
  }
	});

}
///////////////////////////////////////////////////////////////
//Wait to initialize
// $(document).ready(function(){

 // document.addEventListener("DOMContentLoaded", function(event) { 
  // initialize();
  
  // });
//Taken from: https://stackoverflow.com/questions/32808613/how-to-wait-till-the-google-maps-api-has-loaded-before-loading-a-google-maps-ove
var mapWaitCount = 0;
var mapWaitMax = 20;

function map_load() { // if you need any param
    mapWaitCount++;
    // if api is loaded
    if(typeof google !== 'undefined') {
        initialize();
    }
    // try again if until maximum allowed attempt
    else if(mapWaitCount < mapWaitMax) {
        console.log('Waiting attempt #' + mapWaitCount); // just log
        setTimeout(function() { map_load(); }, 1000);
    }
    // if failed after maximum attempt, not mandatory
    else if(mapWaitCount >= mapWaitMax) {
        console.log('Failed to load google api');
    }
}

map_load();
/////////////////////////////////////////////////////
